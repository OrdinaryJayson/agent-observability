"""Business-database experiment metadata; never sends SQL from HTTP to a DB."""

import os

from sqlalchemy import text

from app.core.database import get_engine
from app.core.errors import AppError
from app.lab.database import configured_url
from app.repositories.v2 import audit, encode, one, rows
from app.services.v2_runs import idempotency, save_key

EXPERIMENT_SELECT = """SELECT e.*,
  (SELECT count(*) FROM experiment_trials t WHERE t.experiment_id=e.experiment_id) AS trial_count,
  (SELECT count(*) FROM experiment_samples s JOIN experiment_trials t USING(trial_id) WHERE t.experiment_id=e.experiment_id) AS sample_count
  FROM experiment_runs e"""


def experiment(conn, experiment_id, *, lock=False):
    return one(
        conn,
        EXPERIMENT_SELECT
        + " WHERE experiment_id=:id"
        + (" FOR UPDATE OF e" if lock else ""),
        id=experiment_id,
    )


def register_dataset(body):
    if body.purpose in {"BENCHMARK", "LOAD"}:
        configured_url()
    with get_engine().begin() as conn:
        result = one(
            conn,
            """INSERT INTO dataset_manifests(name,purpose,state,seed,config,actual_counts,generator_version)
          VALUES(:name,:purpose,'BUILDING',:seed,CAST(:config AS jsonb),'{}',:version) RETURNING *""",
            name=body.name,
            purpose=body.purpose,
            seed=body.seed,
            config=encode(body.config),
            version=body.generator_version,
        )
        audit(
            conn,
            "dataset.registered",
            "dataset",
            result["dataset_id"],
            {"purpose": body.purpose},
        )
        return result


def finalize(dataset_id, body):
    with get_engine().connect() as conn:
        one(conn, "SELECT * FROM dataset_manifests WHERE dataset_id=:id", id=dataset_id)
    # The frozen baseline does not define canonical logical records/count keys.
    # Accepting the supplied hash here would falsely certify client assertions.
    raise AppError(
        409,
        "FEATURE_NOT_AVAILABLE",
        "Dataset verification awaits the shared logical-record and manifest contract",
    )


def start(body, key):
    configured_url()
    values = body.model_dump(mode="json")
    with get_engine().begin() as conn:
        hashed, existing = idempotency(conn, "v2:experiments", key, values)
        if existing is not None:
            return existing
        # One short transaction serializes capacity accounting across API processes.
        conn.execute(text("SELECT pg_advisory_xact_lock(90624120)"))
        dataset = one(
            conn,
            "SELECT * FROM dataset_manifests WHERE dataset_id=:id FOR SHARE",
            id=body.dataset_id,
        )
        if dataset["state"] != "READY" or dataset["purpose"] != "BENCHMARK":
            raise AppError(
                409, "CONFLICT", "Experiments require a verified BENCHMARK dataset"
            )
        if (
            conn.scalar(
                text("SELECT count(*) FROM experiment_runs WHERE status='QUEUED'")
            )
            >= 10
        ):
            raise AppError(429, "CONFLICT", "At most ten experiments may queue")
        created = one(
            conn,
            """INSERT INTO experiment_runs(dataset_id,case_code,status,config,environment,protocol_version,code_revision)
          VALUES(:dataset,:case,'QUEUED',CAST(:config AS jsonb),'{}','2.0',:revision) RETURNING experiment_id""",
            dataset=body.dataset_id,
            case=body.case_code,
            config=encode(values),
            revision=os.getenv("CODE_REVISION", "unknown")[:80],
        )
        result = {
            "data": experiment(conn, created["experiment_id"]),
            "message": "accepted",
        }
        save_key(conn, "v2:experiments", key, hashed, created["experiment_id"], result)
        audit(conn, "experiment.queued", "experiment", created["experiment_id"])
        return result


def cancel(experiment_id):
    with get_engine().begin() as conn:
        current = experiment(conn, experiment_id, lock=True)
        if current["status"] not in {"QUEUED", "RUNNING"}:
            return current
        if current["cancel_requested_at"] is None:
            conn.execute(
                text("""UPDATE experiment_runs SET cancel_requested_at=clock_timestamp(),
              status=CASE WHEN status='QUEUED' THEN 'CANCELLED' ELSE status END,
              ended_at=CASE WHEN status='QUEUED' THEN clock_timestamp() ELSE ended_at END WHERE experiment_id=:id"""),
                {"id": experiment_id},
            )
            audit(conn, "experiment.cancel_requested", "experiment", experiment_id)
        return experiment(conn, experiment_id)


def claim(runner_id):
    """Caller must first own the dedicated lab DB's session advisory lock."""
    with get_engine().begin() as conn:
        conn.execute(
            text("""UPDATE experiment_runs SET status='FAILED',ended_at=clock_timestamp(),error_code='EXPERIMENT_TIMEOUT'
          WHERE status='QUEUED' AND created_at<clock_timestamp()-interval '300 seconds'""")
        )
        selected = rows(
            conn,
            "SELECT experiment_id FROM experiment_runs WHERE status='QUEUED' ORDER BY created_at,experiment_id FOR UPDATE SKIP LOCKED LIMIT 1",
        )
        if not selected:
            return None
        return one(
            conn,
            """UPDATE experiment_runs SET status='RUNNING',phase='PREPARING',runner_id=:runner,
          started_at=clock_timestamp() WHERE experiment_id=:id RETURNING *""",
            id=selected[0]["experiment_id"],
            runner=runner_id,
        )


def recover_abandoned(runner_id):
    """Only after acquiring the exclusive lab session lock, never on API startup."""
    with get_engine().begin() as conn:
        abandoned = rows(
            conn,
            """UPDATE experiment_runs SET status='FAILED',ended_at=clock_timestamp(),error_code='EXPERIMENT_INTERRUPTED'
          WHERE status='RUNNING' RETURNING experiment_id""",
        )
        for row in abandoned:
            audit(
                conn,
                "experiment.interrupted",
                "experiment",
                row["experiment_id"],
                actor=runner_id,
            )


def control(experiment_id):
    with get_engine().connect() as conn:
        item = one(
            conn,
            "SELECT status,cancel_requested_at,started_at+interval '900 seconds'<=clock_timestamp() AS expired FROM experiment_runs WHERE experiment_id=:id",
            id=experiment_id,
        )
    if item["expired"]:
        raise AppError(
            504, "EXPERIMENT_TIMEOUT", "Experiment wall-clock budget exhausted"
        )
    if item["cancel_requested_at"] is not None or item["status"] == "CANCELLED":
        raise AppError(409, "EXPERIMENT_CANCELLED", "Experiment cancelled")
    if item["status"] != "RUNNING":
        raise AppError(409, "CONFLICT", "Experiment is no longer owned")


def phase(experiment_id, value, progress=None):
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE experiment_runs SET phase=:phase,progress=:progress WHERE experiment_id=:id AND status='RUNNING'"
            ),
            {"id": experiment_id, "phase": value, "progress": progress},
        )


def finish(experiment_id, runner_id, status, error_code=None):
    with get_engine().begin() as conn:
        result = rows(
            conn,
            """UPDATE experiment_runs SET status=CAST(:status AS varchar),ended_at=clock_timestamp(),error_code=:error,
          progress=CASE WHEN CAST(:status AS varchar)='SUCCESS' THEN 1 ELSE progress END WHERE experiment_id=:id AND status='RUNNING' AND runner_id=:runner RETURNING experiment_id""",
            id=experiment_id,
            runner=runner_id,
            status=status,
            error=error_code,
        )
        if result:
            audit(
                conn,
                "experiment.finished",
                "experiment",
                experiment_id,
                {"status": status, "error_code": error_code},
                actor=runner_id,
            )
