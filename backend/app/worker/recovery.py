from fastapi.encoders import jsonable_encoder

from app.core.database import get_engine
from app.repositories.v2 import audit, journal, one, rows, system_event
from app.services import v2_engine, v2_journal


def recover_one(worker_id):
    with get_engine().begin() as conn:
        candidates = rows(
            conn,
            """SELECT *,clock_timestamp() AS db_now FROM run_executions WHERE
          (execution_state='QUEUED' AND queued_at<=clock_timestamp()-interval '300 seconds') OR
          (execution_state IN ('RUNNING','RECOVERING','FINALIZING') AND
            (lease_expires_at<=clock_timestamp() OR deadline_at<=clock_timestamp()))
          ORDER BY queued_at,run_id FOR UPDATE SKIP LOCKED LIMIT 1""",
        )
        if not candidates:
            return None
        old = candidates[0]
        queued = old["execution_state"] == "QUEUED"
        checkpoint = old["checkpoint"]
        definition_hash = one(
            conn,
            "SELECT definition_hash FROM workflow_versions WHERE version_id=:id",
            id=old["version_id"],
        )["definition_hash"]
        invalid_checkpoint = bool(checkpoint) and (
            checkpoint.get("checkpoint_version") != 1
            or checkpoint.get("definition_hash") != definition_hash
            or checkpoint.get("clock_mode") != old["config"]["mode"]
            or checkpoint.get("journal_seq") != old["last_seq"]
        )
        exhausted = (
            old["recovery_count"] >= 2
            or old["deadline_at"] <= old["db_now"]
            or invalid_checkpoint
        )
        owned = one(
            conn,
            """UPDATE run_executions SET worker_id=:worker,lease_epoch=lease_epoch+1,
          lease_expires_at=clock_timestamp()+interval '15 seconds',heartbeat_at=clock_timestamp(),
          execution_state='RECOVERING',recovery_count=least(2,recovery_count+1)
          WHERE run_id=:id RETURNING *""",
            worker=worker_id,
            id=old["run_id"],
        )
        if queued or exhausted:
            reason = (
                "QueueTimeout"
                if queued
                else "DeadlineExceeded"
                if old["deadline_at"] <= old["db_now"]
                else "CheckpointInvalid"
                if invalid_checkpoint
                else "WorkerLost"
            )
            complete = True
            projection = {
                "spans": [],
                "events": [],
                "links": [],
                "final_status": "FAILED",
                "error_summary": reason,
                "logical_duration_ms": None,
            }
            if not queued:
                try:
                    projection = v2_engine.seal_interrupted(
                        jsonable_encoder(journal(conn, old["run_id"])),
                        reason,
                        old["db_now"],
                    )
                    projection["final_status"] = "FAILED"
                except Exception:
                    complete = False
                    audit(
                        conn,
                        "run.projection_unavailable",
                        "run",
                        old["run_id"],
                        {"reason": reason},
                        actor=worker_id,
                    )
            # Projection failure itself must not leave partially inserted spans.
            try:
                with conn.begin_nested():
                    v2_journal.project_terminal(
                        conn, owned, projection, complete=complete
                    )
            except Exception:
                projection = {
                    "spans": [],
                    "events": [],
                    "links": [],
                    "final_status": "FAILED",
                    "error_summary": reason + ": incomplete trace",
                    "logical_duration_ms": None,
                }
                v2_journal.project_terminal(conn, owned, projection, complete=False)
                audit(
                    conn,
                    "run.projection_unavailable",
                    "run",
                    old["run_id"],
                    {"reason": reason},
                    actor=worker_id,
                )
            return {"finished": True, "run_id": old["run_id"]}
        seq = system_event(
            conn,
            old["run_id"],
            "run.recovering",
            {
                "lease_epoch": owned["lease_epoch"],
                "recovery_count": owned["recovery_count"],
            },
            owned["lease_epoch"],
        )
        owned["last_seq"] = seq
        if owned["checkpoint"]:
            owned["checkpoint"]["journal_seq"] = seq
        audit(
            conn,
            "run.recovering",
            "run",
            old["run_id"],
            {"epoch": owned["lease_epoch"]},
            actor=worker_id,
        )
        return owned
