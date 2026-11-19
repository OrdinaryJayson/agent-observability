import asyncio
import json
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from app.api.query import validate_query_names
from app.contracts.v2 import RunStart, utc
from app.core.database import get_engine, read_snapshot
from app.core.errors import AppError
from app.repositories.v2 import one
from app.schemas.v2 import (
    CursorQuery,
    DraftValidation,
    Empty,
    JournalQuery,
    Publish,
    RunQuery,
    StreamQuery,
    WorkflowCreate,
    WorkflowPatch,
)
from app.services import v2_engine, v2_journal, v2_queries, v2_runs, v2_workflows

router = APIRouter(
    prefix="/api/v2",
    dependencies=[Depends(validate_query_names)],
    responses={
        code: {"description": "V2 contract error"}
        for code in (409, 410, 412, 422, 428, 429, 504)
    },
)
Q = Annotated[CursorQuery, Query()]


def envelope(value):
    return {"data": value, "message": "success"}


@router.get("/capabilities")
def capabilities():
    # Enable only independently verified components; C availability is explicit.
    return envelope(
        {
            "protocol_version": "2.0",
            "features": {
                "workflow_editor": False,
                "durable_queue": False,
                "live_graph": False,
                "experiments": False,
                "trace_search": True,
                "aggregates": True,
                "database_catalog": True,
                "audit": True,
                "analytics_series": False,
                "dataset_loader": False,
                "comparisons": False,
            },
            "limits": {
                "nodes": 50,
                "edges": 100,
                "spans": 500,
                "span_events": 2000,
                "journal_events": 5000,
                "max_parallelism": 4,
            },
            "scenarios": ["RESEARCH_PIPELINE", "PARALLEL_RETRIEVAL", "QUALITY_GATE"],
            "algorithm_version": "2.0",
            "experiment_protocol_version": "2.0",
        }
    )


@router.post("/workflows", status_code=201)
def create_workflow(body: WorkflowCreate):
    return envelope(v2_workflows.create(body.model_dump(mode="json")))


@router.get("/workflows")
def workflows(query: Q):
    with get_engine().connect() as conn:
        return v2_queries.cursor_page(
            conn,
            "SELECT * FROM workflows",
            {},
            query,
            [("created_at", "timestamptz", utc), ("workflow_id", "uuid", UUID)],
            "workflows",
        )


@router.get("/workflows/{id}")
def workflow(id: UUID):
    with get_engine().connect() as conn:
        return envelope(
            one(conn, "SELECT * FROM workflows WHERE workflow_id=:id", id=id)
        )


@router.patch("/workflows/{id}")
def patch_workflow(
    id: UUID, body: WorkflowPatch, if_match: Annotated[str | None, Header()] = None
):
    return envelope(
        v2_workflows.update(
            id,
            body.model_dump(mode="json", exclude_unset=True),
            v2_workflows.revision(if_match),
        )
    )


@router.post("/workflows/{id}/validate")
def validate_workflow(id: UUID, body: DraftValidation):
    workflow(id)
    return envelope(v2_engine.validate_workflow(body.draft.root))


@router.post("/workflows/{id}/versions", status_code=201)
def publish_workflow(
    id: UUID, body: Publish, if_match: Annotated[str | None, Header()] = None
):
    return envelope(
        v2_workflows.publish(
            id, v2_workflows.revision(if_match), body.expected_definition_hash
        )
    )


@router.get("/workflows/{id}/versions")
def versions(id: UUID, query: Q):
    with get_engine().connect() as conn:
        one(conn, "SELECT workflow_id FROM workflows WHERE workflow_id=:id", id=id)
        return v2_queries.cursor_page(
            conn,
            "SELECT * FROM workflow_versions WHERE workflow_id=:id",
            {"id": id},
            query,
            [("created_at", "timestamptz", utc), ("version_id", "uuid", UUID)],
            f"versions:{id}",
        )


@router.get("/workflow-versions/{id}")
def version(id: UUID):
    with get_engine().connect() as conn:
        return envelope(
            one(conn, "SELECT * FROM workflow_versions WHERE version_id=:id", id=id)
        )


@router.post("/tasks/{task_id}/runs", status_code=202)
def start_run(
    task_id: UUID,
    body: RunStart,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    return v2_runs.start(task_id, body, idempotency_key)


@router.get("/runs/{run_id}")
def run(run_id: UUID):
    with read_snapshot() as conn:
        return envelope(v2_queries.run_view(conn, run_id))


@router.get("/runs")
def runs(query: Annotated[RunQuery, Query()]):
    conditions = []
    parameters = {}
    for key, column in {
        "task_id": "r.task_id",
        "version_id": "e.version_id",
        "status": "r.status",
        "execution_state": "e.execution_state",
        "mode": "coalesce(e.config->>'mode','LEGACY')",
    }.items():
        value = getattr(query, key)
        if value is not None:
            conditions.append(f"{column}=:{key}")
            parameters[key] = value
    for key, operator in (("from_time", ">="), ("to_time", "<")):
        if getattr(query, key) is not None:
            conditions.append(f"coalesce(e.queued_at,r.created_at){operator}:{key}")
            parameters[key] = getattr(query, key)
    sql = (
        "SELECT r.run_id,coalesce(e.queued_at,r.created_at) AS order_at FROM runs r LEFT JOIN run_executions e USING(run_id) WHERE "
        + (" AND ".join(conditions) or "TRUE")
    )
    with get_engine().connect() as conn:
        result = v2_queries.cursor_page(
            conn,
            sql,
            parameters,
            query,
            [("order_at", "timestamptz", utc), ("run_id", "uuid", UUID)],
            "runs",
        )
        result["data"] = [
            v2_queries.run_view(conn, r["run_id"]) for r in result["data"]
        ]
        return result


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: UUID, body: Empty):
    accepted, terminal = v2_journal.cancel(run_id)
    return envelope(
        {"accepted": accepted, "already_terminal": terminal, "run": run(run_id)["data"]}
    )


@router.get("/runs/{run_id}/snapshot")
def snapshot(run_id: UUID):
    with read_snapshot() as conn:
        return envelope(v2_queries.snapshot(conn, run_id))


@router.get("/runs/{run_id}/journal")
def journal(run_id: UUID, query: Annotated[JournalQuery, Query()]):
    with read_snapshot() as conn:
        return v2_queries.journal_page(conn, run_id, query.after_seq, query.limit)


@router.get("/runs/{run_id}/stream")
def stream(
    run_id: UUID,
    request: Request,
    query: Annotated[StreamQuery, Query()],
    last_event_id: Annotated[str | None, Header()] = None,
):
    after = query.after_seq or 0
    if last_event_id is not None:
        if (
            not last_event_id.isascii()
            or not last_event_id.isdigit()
            or len(last_event_id) > 16
        ):
            raise AppError(422, "VALIDATION_ERROR", "Invalid Last-Event-ID")
        header = int(last_event_id)
        if query.after_seq is not None and header != query.after_seq:
            raise AppError(422, "VALIDATION_ERROR", "Conflicting journal cursors")
        after = header

    def read(position):
        with read_snapshot() as conn:
            page = v2_queries.journal_page(conn, run_id, position, 100)
            terminal = (
                one(
                    conn,
                    "SELECT execution_state FROM run_executions WHERE run_id=:id",
                    id=run_id,
                )["execution_state"]
                == "FINISHED"
            )
            return page, terminal

    initial = read(after)  # JSON validation errors must precede streaming headers.

    async def generate():
        position = after
        page, terminal = initial
        heartbeat = time.monotonic()
        try:
            while not await request.is_disconnected():
                for event in page["data"]:
                    position = event["seq"]
                    data = json.dumps(
                        jsonable_encoder(event),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield f"id: {position}\nevent: {event['kind']}\ndata: {data}\n\n"
                    if event["kind"] == "run.finished":
                        return
                if terminal and position == page["meta"]["snapshot_seq"]:
                    yield "event: stream.end\ndata: {}\n\n"
                    return
                if time.monotonic() - heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0 if page["meta"]["has_more"] else 0.5)
                page, terminal = await asyncio.to_thread(read, position)
        except asyncio.CancelledError:
            raise
        except Exception:
            yield 'event: stream.error\ndata: {"code":"INTERNAL_ERROR"}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
