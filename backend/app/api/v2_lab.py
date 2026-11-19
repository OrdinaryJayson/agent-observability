import csv
import io
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder

from app.api.query import validate_query_names
from app.api.v2 import envelope
from app.contracts.v2 import utc
from app.core.database import get_engine, read_snapshot
from app.core.errors import AppError
from app.repositories.v2 import one, rows
from app.schemas.v2 import CursorQuery, Empty
from app.schemas.v2_lab import (
    DatasetCreate,
    DatasetFinalize,
    ExperimentRequest,
    ExportQuery,
    SampleQuery,
)
from app.services import v2_lab, v2_queries

router = APIRouter(prefix="/api/v2", dependencies=[Depends(validate_query_names)])


@router.post("/datasets", status_code=201)
def register_dataset(body: DatasetCreate):
    return envelope(v2_lab.register_dataset(body))


@router.get("/datasets")
def datasets(query: Annotated[CursorQuery, Query()]):
    with get_engine().connect() as conn:
        return v2_queries.cursor_page(
            conn,
            "SELECT * FROM dataset_manifests",
            {},
            query,
            [("created_at", "timestamptz", utc), ("dataset_id", "uuid", UUID)],
            "datasets",
        )


@router.get("/datasets/{id}")
def dataset(id: UUID):
    with get_engine().connect() as conn:
        return envelope(
            one(conn, "SELECT * FROM dataset_manifests WHERE dataset_id=:id", id=id)
        )


@router.post("/datasets/{id}/finalize")
def finalize(id: UUID, body: DatasetFinalize):
    return envelope(v2_lab.finalize(id, body))


@router.post("/experiments", status_code=202)
def create_experiment(
    body: ExperimentRequest, idempotency_key: Annotated[str | None, Header()] = None
):
    return v2_lab.start(body, idempotency_key)


@router.get("/experiments")
def experiments(query: Annotated[CursorQuery, Query()]):
    with get_engine().connect() as conn:
        return v2_queries.cursor_page(
            conn,
            v2_lab.EXPERIMENT_SELECT,
            {},
            query,
            [("created_at", "timestamptz", utc), ("experiment_id", "uuid", UUID)],
            "experiments",
        )


@router.get("/experiments/{id}")
def experiment(id: UUID):
    with get_engine().connect() as conn:
        return envelope(v2_lab.experiment(conn, id))


@router.post("/experiments/{id}/cancel")
def cancel(id: UUID, body: Empty):
    return envelope(v2_lab.cancel(id))


@router.get("/experiments/{id}/trials")
def trials(id: UUID, query: Annotated[CursorQuery, Query()]):
    with get_engine().connect() as conn:
        v2_lab.experiment(conn, id)
        return v2_queries.cursor_page(
            conn,
            "SELECT * FROM experiment_trials WHERE experiment_id=:id",
            {"id": id},
            query,
            [("ordinal", "integer", int), ("trial_id", "uuid", UUID)],
            f"trials:{id}",
        )


@router.get("/experiments/{id}/samples")
def samples(id: UUID, query: Annotated[SampleQuery, Query()]):
    with get_engine().connect() as conn:
        one(
            conn,
            "SELECT trial_id FROM experiment_trials WHERE experiment_id=:id AND trial_id=:trial",
            id=id,
            trial=query.trial_id,
        )
        return v2_queries.cursor_page(
            conn,
            "SELECT * FROM experiment_samples WHERE trial_id=:trial",
            {"trial": query.trial_id},
            query,
            [("repetition", "integer", int)],
            f"samples:{id}",
        )


@router.get("/experiments/{id}/export")
def export(id: UUID, query: Annotated[ExportQuery, Query()]):
    # Bound before serialization and before sending headers; the returned stream
    # owns bytes, not a pooled database connection.
    with read_snapshot() as conn:
        experiment = v2_lab.experiment(conn, id)
        if experiment["status"] in {"QUEUED", "RUNNING"}:
            raise AppError(409, "CONFLICT", "Only terminal experiments can be exported")
        size = one(
            conn,
            """SELECT coalesce(sum(pg_column_size(s)),0) AS size FROM experiment_samples s
          JOIN experiment_trials t USING(trial_id) WHERE experiment_id=:id""",
            id=id,
        )["size"]
        if size > 50 * 1024 * 1024:
            raise AppError(
                422,
                "BUDGET_EXCEEDED",
                "Export exceeds 50 MiB; download paginated trials and samples",
            )
        dataset = one(
            conn,
            "SELECT * FROM dataset_manifests WHERE dataset_id=:id",
            id=experiment["dataset_id"],
        )
        trials = rows(
            conn,
            "SELECT * FROM experiment_trials WHERE experiment_id=:id ORDER BY ordinal",
            id=id,
        )
        samples = rows(
            conn,
            "SELECT s.* FROM experiment_samples s JOIN experiment_trials t USING(trial_id) WHERE experiment_id=:id ORDER BY ordinal,repetition",
            id=id,
        )
    if query.format == "json":
        content = json.dumps(
            jsonable_encoder(
                {
                    "protocol_version": "2.0",
                    "dataset": dataset,
                    "experiment": experiment,
                    "trials": trials,
                    "samples": samples,
                }
            ),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        media_type = "application/json"
    else:
        fields = [
            "trial_id",
            "repetition",
            "is_warmup",
            "measured_at",
            "execution_ms",
            "client_ms",
            "returned_rows",
            "scanned_rows",
            "shared_hit_blocks",
            "shared_read_blocks",
            "local_hit_blocks",
            "temp_read_blocks",
            "index_bytes",
            "insert_ms",
            "passed",
            "result_hash",
        ]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for sample in samples:
            writer.writerow({**sample, **sample["metrics"], **sample["correctness"]})
        content = stream.getvalue().encode("utf-8")
        media_type = "text/csv"
    if len(content) > 50 * 1024 * 1024:
        raise AppError(
            422,
            "BUDGET_EXCEEDED",
            "Export exceeds 50 MiB; download paginated trials and samples",
        )
    return StreamingResponse(
        (content[i : i + 65536] for i in range(0, len(content), 65536)),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="experiment-{id}.{query.format}"'
        },
    )
