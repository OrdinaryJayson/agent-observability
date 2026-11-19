"""Atomic journal receipts, checkpoints and terminal five-table projection."""

import copy
import json
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import insert, text

from app.contracts.v2 import JournalBatch, digest
from app.core.database import get_engine
from app.core.errors import AppError
from app.models.tables import tables
from app.repositories.v2 import audit, encode, journal, one, rows, system_event
from app.services import v2_engine, v2_runs, v2_projection
from app.services.run_completion import validate_result


def semantic_hash(batch):
    value = copy.deepcopy(batch)
    value.pop("lease_epoch")
    value.pop("expected_last_seq")
    value["checkpoint"].pop("journal_seq")
    return digest(value)


def project_terminal(
    conn, execution, projection, *, complete=True, batch_id=None, batch_hash=None
):
    run_id = execution["run_id"]
    run = one(conn, "SELECT * FROM runs WHERE run_id=:id FOR UPDATE", id=run_id)
    if run["status"] != "RUNNING":
        raise AppError(409, "CONFLICT", "Run already finished")
    status = projection["final_status"]
    if status not in {"SUCCESS", "FAILED", "CANCELLED"}:
        raise AppError(422, "VALIDATION_ERROR", "Invalid terminal status")
    spans, events = projection["spans"], projection["events"]
    if spans:
        spans, events = validate_result(spans, events)
    elif events or status == "SUCCESS":
        raise AppError(422, "VALIDATION_ERROR", "Invalid empty projection")
    v2_projection.validate(conn, execution, spans, projection.get("links", []), status)
    t = tables()
    if spans:
        conn.execute(insert(t["spans"]), [{**s, "run_id": run_id} for s in spans])
    if events:
        conn.execute(
            insert(t["span_events"]), [{**e, "run_id": run_id} for e in events]
        )
    for link in projection.get("links", []):
        conn.execute(
            text("""INSERT INTO span_links(run_id,source_span_id,target_span_id,link_type)
          VALUES(:id,:source,:target,:kind)"""),
            {
                "id": run_id,
                "source": link["source_span_id"],
                "target": link["target_span_id"],
                "kind": link["link_type"],
            },
        )
    seq = system_event(
        conn,
        run_id,
        "run.finished",
        {
            "status": status,
            "error_summary": projection.get("error_summary"),
            "projection_complete": complete,
        },
        execution["lease_epoch"],
        batch_id,
        batch_hash,
    )
    ended = conn.execute(
        text("""UPDATE runs SET status=:status,ended_at=greatest(started_at,clock_timestamp()),error_summary=:error
      WHERE run_id=:id RETURNING ended_at"""),
        {"id": run_id, "status": status, "error": projection.get("error_summary")},
    ).scalar_one()
    checkpoint = copy.deepcopy(execution["checkpoint"])
    if checkpoint:
        checkpoint["journal_seq"] = seq
    conn.execute(
        text("""UPDATE run_executions SET execution_state='FINISHED',execution_ended_at=:ended,
      worker_id=NULL,lease_expires_at=NULL,checkpoint=CAST(:checkpoint AS jsonb) WHERE run_id=:id"""),
        {"id": run_id, "ended": ended, "checkpoint": encode(checkpoint)},
    )
    started = execution["execution_started_at"]
    conn.execute(
        text("""INSERT INTO run_summaries(run_id,finalized_at,run_started_at,final_status,execution_mode,
      span_count,event_count,error_count,input_tokens,output_tokens,wall_duration_ms,queue_duration_ms,
      execution_duration_ms,logical_duration_ms,journal_seq)
      VALUES(:id,:ended,:started,:status,:mode,:spans,:events,:errors,:input,:output,:wall,:queue,:execution,:logical,:seq)"""),
        {
            "id": run_id,
            "ended": ended,
            "started": run["started_at"],
            "status": status,
            "mode": execution["config"]["mode"],
            "spans": len(spans),
            "events": len(events),
            "errors": sum(s["status"] == "ERROR" for s in spans),
            "input": sum(
                s.get("input_tokens") or 0
                for s in spans
                if s["operation_type"] == "LLM"
            ),
            "output": sum(
                s.get("output_tokens") or 0
                for s in spans
                if s["operation_type"] == "LLM"
            ),
            "wall": max(0, (ended - run["started_at"]).total_seconds() * 1000),
            "queue": max(
                0, ((started or ended) - execution["queued_at"]).total_seconds() * 1000
            ),
            "execution": max(0, (ended - started).total_seconds() * 1000)
            if started
            else 0,
            "logical": projection.get("logical_duration_ms"),
            "seq": seq,
        },
    )
    audit(
        conn,
        "run.finished",
        "run",
        run_id,
        {"status": status, "projection_complete": complete},
        actor=execution["worker_id"] or "LOCAL_OPERATOR",
    )
    return seq


def commit(worker_id, batch):
    value = JournalBatch.model_validate(batch).root
    hashed = semantic_hash(value)
    run_id = UUID(value["run_id"])
    with get_engine().begin() as conn:
        owned = v2_runs.lock_execution(conn, run_id)
        receipts = rows(
            conn,
            """SELECT min(seq) AS first_seq,max(seq) AS last_seq,min(batch_hash) AS hash,
          bool_or(kind='run.finished') AS terminal_committed FROM run_journal
          WHERE run_id=:id AND batch_id=:batch HAVING count(*)>0""",
            id=run_id,
            batch=UUID(value["batch_id"]),
        )
        if receipts:
            receipt = receipts[0]
            if receipt.pop("hash") != hashed:
                raise AppError(409, "IDEMPOTENCY_CONFLICT", "Batch content changed")
            return {
                "run_id": str(run_id),
                "batch_id": value["batch_id"],
                **receipt,
                "duplicate": True,
            }
        v2_runs.require_lease(owned, worker_id, value["lease_epoch"])
        if owned["last_seq"] != value["expected_last_seq"]:
            raise AppError(
                409,
                "CHECKPOINT_CONFLICT",
                "Journal advanced",
                {"last_seq": owned["last_seq"]},
            )
        version = one(
            conn,
            "SELECT definition_hash FROM workflow_versions WHERE version_id=:id",
            id=owned["version_id"],
        )
        checkpoint = copy.deepcopy(value["checkpoint"])
        if (
            checkpoint["definition_hash"] != version["definition_hash"]
            or checkpoint["clock_mode"] != owned["config"]["mode"]
            or checkpoint["journal_seq"] != value["expected_last_seq"]
        ):
            raise AppError(
                422, "VALIDATION_ERROR", "Checkpoint does not match execution"
            )
        producers = [UUID(e["producer_event_id"]) for e in value["events"]]
        if conn.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM run_journal WHERE run_id=:id AND producer_event_id=ANY(:ids))"
            ),
            {"id": run_id, "ids": producers},
        ).scalar_one():
            raise AppError(
                409, "IDEMPOTENCY_CONFLICT", "Producer event was used in another batch"
            )
        terminal = value["terminal"]
        last_seq = owned["last_seq"] + len(value["events"])
        if last_seq + (1 if terminal else 0) > (5000 if terminal else 4936):
            raise AppError(422, "BUDGET_EXCEEDED", "Journal budget exhausted")
        for offset, event in enumerate(value["events"], owned["last_seq"] + 1):
            conn.execute(
                text("""INSERT INTO run_journal(run_id,seq,batch_id,batch_hash,producer_event_id,kind,payload,payload_hash,lease_epoch,occurred_at)
              VALUES(:id,:seq,:batch,:hash,:event,:kind,CAST(:payload AS jsonb),:phash,:epoch,:at)"""),
                {
                    "id": run_id,
                    "seq": offset,
                    "batch": UUID(value["batch_id"]),
                    "hash": hashed,
                    "event": UUID(event["producer_event_id"]),
                    "kind": event["kind"],
                    "payload": encode(event["payload"]),
                    "phash": digest(event["payload"]),
                    "epoch": value["lease_epoch"],
                    "at": event["occurred_at"],
                },
            )
        projection = v2_engine.reduce_journal(jsonable_encoder(journal(conn, run_id)))
        # A slow pure reducer must not extend a lease by holding this row lock.
        owned["db_now"] = conn.scalar(text("SELECT clock_timestamp()"))
        v2_runs.require_lease(owned, worker_id, value["lease_epoch"])
        if len(projection["spans"]) > 500 or len(projection["events"]) > (
            2000 if terminal else 1984
        ):
            raise AppError(422, "BUDGET_EXCEEDED", "Projection budget exhausted")
        live_bytes = len(
            json.dumps(
                {k: projection[k] for k in ("nodes", "spans", "links")},
                ensure_ascii=False,
            ).encode("utf-8")
        )
        if live_bytes > 2 * 1024 * 1024:
            raise AppError(
                422, "BUDGET_EXCEEDED", "Live projection exceeds the snapshot budget"
            )
        checkpoint["journal_seq"] = last_seq
        conn.execute(
            text(
                "UPDATE run_executions SET last_seq=:seq,checkpoint=CAST(:checkpoint AS jsonb) WHERE run_id=:id"
            ),
            {"id": run_id, "seq": last_seq, "checkpoint": encode(checkpoint)},
        )
        owned["checkpoint"] = checkpoint
        if terminal:
            closed = projection["closed_result"]
            if (
                closed is None
                or closed["final_status"] != terminal["status"]
                or closed.get("error_summary") != terminal["error_summary"]
            ):
                raise AppError(
                    422, "VALIDATION_ERROR", "Terminal projection does not match batch"
                )
            last_seq = project_terminal(
                conn, owned, closed, batch_id=UUID(value["batch_id"]), batch_hash=hashed
            )
        return {
            "run_id": str(run_id),
            "batch_id": value["batch_id"],
            "first_seq": owned["last_seq"] + 1,
            "last_seq": last_seq,
            "duplicate": False,
            "terminal_committed": terminal is not None,
        }


def cancel(run_id):
    with get_engine().begin() as conn:
        owned = v2_runs.lock_execution(conn, run_id)
        if owned["execution_state"] == "FINISHED":
            return False, True
        if owned["cancel_requested_at"] is None:
            conn.execute(
                text(
                    "UPDATE run_executions SET cancel_requested_at=clock_timestamp() WHERE run_id=:id"
                ),
                {"id": run_id},
            )
            system_event(conn, run_id, "cancel.requested", {}, owned["lease_epoch"])
            audit(conn, "run.cancel_requested", "run", run_id)
        if owned["execution_state"] == "QUEUED":
            project_terminal(
                conn,
                owned,
                {
                    "spans": [],
                    "events": [],
                    "links": [],
                    "final_status": "CANCELLED",
                    "error_summary": "Cancelled before execution",
                    "logical_duration_ms": 0,
                },
            )
        return True, False
