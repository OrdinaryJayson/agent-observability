"""Persistent run creation, queue ownership and control transactions."""

import os
import re

from sqlalchemy import make_url, text

from app.contracts.v2 import RunStart, digest
from app.core.config import database_url
from app.core.database import get_engine
from app.core.errors import AppError
from app.repositories import execution, resources
from app.repositories.v2 import audit, encode, one, rows, system_event
from app.services import v2_engine


def idempotency(conn, scope, key, body):
    if key is None or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", key):
        raise AppError(422, "VALIDATION_ERROR", "A valid Idempotency-Key is required")
    hashed = digest(body)
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": scope + ":" + key},
    )
    existing = rows(
        conn,
        "SELECT * FROM request_keys WHERE scope=:scope AND key=:key",
        scope=scope,
        key=key,
    )
    if existing:
        if existing[0]["request_hash"] != hashed:
            raise AppError(
                409, "IDEMPOTENCY_CONFLICT", "Key was used with different content"
            )
        return hashed, existing[0]["response_body"]
    return hashed, None


def save_key(conn, scope, key, hashed, resource_id, response, status=202):
    conn.execute(
        text("""INSERT INTO request_keys(scope,key,request_hash,resource_id,response_status,response_body)
      VALUES(:scope,:key,:hash,:id,:status,CAST(:body AS jsonb))"""),
        {
            "scope": scope,
            "key": key,
            "hash": hashed,
            "id": resource_id,
            "status": status,
            "body": encode(response),
        },
    )


def start(task_id, body: RunStart, key):
    values = body.model_dump(mode="json")
    scope = f"v2:tasks:{task_id}:runs"
    with get_engine().begin() as conn:
        hashed, existing = idempotency(conn, scope, key, values)
        if existing is not None:
            return existing
        resources.get_resource(conn, "tasks", task_id)
        version = one(
            conn,
            """SELECT v.*,w.archived_at FROM workflow_versions v
          JOIN workflows w USING(workflow_id) WHERE version_id=:id FOR SHARE OF w""",
            id=body.version_id,
        )
        if version["archived_at"] is not None:
            raise AppError(409, "CONFLICT", "Workflow is archived")
        report = v2_engine.validate_workflow(version["definition"])
        if not report["valid"]:
            raise AppError(422, "WORKFLOW_INVALID", "Workflow is invalid", report)
        roles = {role["role_key"] for role in version["definition"]["roles"]}
        if (body.unbound and body.agent_bindings) or (
            not body.unbound and set(body.agent_bindings) != roles
        ):
            raise AppError(
                422, "VALIDATION_ERROR", "Bindings must match workflow roles"
            )
        resources.validate_agents(conn, list(set(body.agent_bindings.values())))
        if body.mode == "VIRTUAL":
            name = make_url(database_url()).database or ""
            if (
                os.getenv("TESTDATA_ENABLED", "false").lower() != "true"
                or not name.endswith(("_test", "_lab"))
                or body.dataset_id is None
            ):
                raise AppError(
                    409,
                    "FEATURE_NOT_AVAILABLE",
                    "Virtual execution requires an isolated data service",
                )
        if body.dataset_id:
            one(
                conn,
                "SELECT dataset_id FROM dataset_manifests WHERE dataset_id=:id",
                id=body.dataset_id,
            )
        if body.retry_of_run_id:
            previous = one(
                conn,
                "SELECT r.task_id,r.status,e.version_id FROM runs r JOIN run_executions e USING(run_id) WHERE run_id=:id",
                id=body.retry_of_run_id,
            )
            if (
                previous["task_id"] != task_id
                or previous["version_id"] != body.version_id
                or previous["status"] == "RUNNING"
            ):
                raise AppError(
                    422,
                    "VALIDATION_ERROR",
                    "Retry must reference a terminal run of this task and version",
                )
        run = execution.create_run(conn, task_id)
        conn.execute(
            text("""INSERT INTO run_executions(run_id,version_id,config,agent_bindings,priority,deadline_at,retry_of_run_id)
          VALUES(:id,:version,CAST(:config AS jsonb),CAST(:bindings AS jsonb),:priority,clock_timestamp()+interval '600 seconds',:retry)"""),
            {
                "id": run["run_id"],
                "version": body.version_id,
                "config": encode(values),
                "bindings": encode(values["agent_bindings"]),
                "priority": body.priority,
                "retry": body.retry_of_run_id,
            },
        )
        system_event(
            conn, run["run_id"], "run.queued", {"execution_state": "QUEUED"}, 0
        )
        response = {
            "data": {
                "run_id": str(run["run_id"]),
                "trace_id": run["trace_id"],
                "execution_state": "QUEUED",
                "status": "RUNNING",
                "version_id": str(body.version_id),
            },
            "message": "accepted",
        }
        save_key(conn, scope, key, hashed, run["run_id"], response)
        audit(conn, "run.queued", "run", run["run_id"])
        return response


def claim(worker_id):
    with get_engine().begin() as conn:
        candidates = rows(
            conn,
            """SELECT * FROM run_executions WHERE execution_state='QUEUED'
          AND queued_at > clock_timestamp()-interval '300 seconds' AND deadline_at>clock_timestamp()
          ORDER BY (queued_at < clock_timestamp()-interval '30 seconds') DESC,
          CASE WHEN queued_at < clock_timestamp()-interval '30 seconds' THEN queued_at END ASC,
          priority DESC,queued_at,run_id FOR UPDATE SKIP LOCKED LIMIT 1""",
        )
        if not candidates:
            return None
        row = candidates[0]
        owned = one(
            conn,
            """UPDATE run_executions SET execution_state='RUNNING',worker_id=:worker,
          lease_epoch=lease_epoch+1,lease_expires_at=clock_timestamp()+interval '15 seconds',heartbeat_at=clock_timestamp(),
          execution_started_at=coalesce(execution_started_at,clock_timestamp()) WHERE run_id=:id RETURNING *""",
            worker=worker_id,
            id=row["run_id"],
        )
        seq = system_event(
            conn,
            row["run_id"],
            "run.started",
            {"lease_epoch": owned["lease_epoch"]},
            owned["lease_epoch"],
        )
        owned["last_seq"] = seq
        audit(
            conn,
            "run.started",
            "run",
            row["run_id"],
            {"epoch": owned["lease_epoch"]},
            actor=worker_id,
        )
        return owned


def control(run_id, worker_id, epoch, renew=False):
    with get_engine().begin() as conn:
        if renew:
            conn.execute(
                text("""UPDATE run_executions SET heartbeat_at=clock_timestamp(),lease_expires_at=clock_timestamp()+interval '15 seconds'
              WHERE run_id=:id AND worker_id=:worker AND lease_epoch=:epoch AND lease_expires_at>clock_timestamp()
              AND deadline_at>clock_timestamp() AND execution_state<>'FINISHED'"""),
                {"id": run_id, "worker": worker_id, "epoch": epoch},
            )
        return one(
            conn,
            """SELECT cancel_requested_at IS NOT NULL AS cancel_requested,
          coalesce(worker_id=:worker AND lease_epoch=:epoch AND lease_expires_at>clock_timestamp()
            AND deadline_at>clock_timestamp() AND execution_state<>'FINISHED',false) AS lease_valid,deadline_at,last_seq
          FROM run_executions WHERE run_id=:id""",
            id=run_id,
            worker=worker_id,
            epoch=epoch,
        )


def lock_execution(conn, run_id):
    return one(
        conn,
        "SELECT *,clock_timestamp() AS db_now FROM run_executions WHERE run_id=:id FOR UPDATE",
        id=run_id,
    )


def require_lease(row, worker_id, epoch):
    if (
        row["worker_id"] != worker_id
        or row["lease_epoch"] != epoch
        or row["lease_expires_at"] is None
        or row["lease_expires_at"] <= row["db_now"]
        or row["deadline_at"] <= row["db_now"]
        or row["execution_state"] == "FINISHED"
    ):
        raise AppError(409, "LEASE_LOST", "Worker no longer owns an active lease")
