from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from app.core.database import get_engine, read_snapshot
from app.core.errors import AppError
from app.repositories.v2 import encode, journal, one, rows
from app.services import v2_engine
from app.services.v2_queries import run_view


def inputs(conn, run_id):
    run = run_view(conn, run_id)
    if run["status"] == "RUNNING":
        raise AppError(409, "CONFLICT", "Analysis requires a terminal run")
    if run["mode"] == "LEGACY":
        return run, None, None
    version = one(
        conn,
        "SELECT definition FROM workflow_versions WHERE version_id=:id",
        id=run["version_id"],
    )
    projected = v2_engine.reduce_journal(jsonable_encoder(journal(conn, run_id)))
    if projected["closed_result"] is None:
        raise AppError(409, "CONFLICT", "Run has no complete projection")
    return run, version["definition"], projected["closed_result"]


def analyze(run_id):
    with read_snapshot() as conn:
        run = run_view(conn, run_id)
        if run["status"] == "RUNNING":
            raise AppError(409, "CONFLICT", "Analysis requires a terminal run")
        if run["mode"] == "LEGACY":
            return {
                "supported": False,
                "reason": "LEGACY runs only have a static terminal trace",
            }
        cached = rows(
            conn,
            "SELECT report FROM analysis_reports WHERE run_id=:id AND journal_seq=:seq AND algorithm_version='2.0'",
            id=run_id,
            seq=run["last_seq"],
        )
        if cached:
            return cached[0]["report"]
        run, definition, projection = inputs(conn, run_id)
    report = v2_engine.plain(
        v2_engine.function("analyze_run")(
            definition=definition, projection=projection, algorithm_version="2.0"
        )
    )
    report["journal_seq"] = run["last_seq"]
    with get_engine().begin() as conn:
        conn.execute(
            text("""INSERT INTO analysis_reports(run_id,journal_seq,algorithm_version,report)
          VALUES(:id,:seq,'2.0',CAST(:report AS jsonb)) ON CONFLICT DO NOTHING"""),
            {"id": run_id, "seq": run["last_seq"], "report": encode(report)},
        )
    return report


def compare(run_ids):
    with read_snapshot() as conn:
        values = [run_view(conn, run_id) for run_id in run_ids]
    if (
        any(r["mode"] == "LEGACY" for r in values)
        or len({(r["version_id"], r["mode"]) for r in values}) != 1
    ):
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "Comparison requires the same version and clock mode",
        )
    if any(r["status"] == "RUNNING" for r in values):
        raise AppError(409, "CONFLICT", "Comparison requires terminal runs")
    # ComparisonInput's exact record shape must be frozen by the project lead.
    raise AppError(
        409,
        "FEATURE_NOT_AVAILABLE",
        "ComparisonInput adapter awaits the shared record contract",
    )
