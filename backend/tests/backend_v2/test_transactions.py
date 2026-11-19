from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.errors import AppError
from app.services import v2_runs, v2_workflows, v2_journal


def test_idempotency_and_competing_claims(prepared, db):
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: prepared["start"](), range(2)))
    assert results[0] == results[1]
    with db.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM runs")) == 1
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(v2_runs.claim, ["worker-a", "worker-b"]))
    claim = next(c for c in claims if c)
    assert sum(c is not None for c in claims) == 1
    assert claim["lease_epoch"] == 1 and claim["last_seq"] == 2
    assert v2_runs.control(claim["run_id"], claim["worker_id"], 1)["lease_valid"]
    assert not v2_runs.control(claim["run_id"], claim["worker_id"], 0, renew=True)[
        "lease_valid"
    ]


def test_revision_conflict_and_immutable_records(prepared, db):
    workflow = prepared["workflow"]
    with pytest.raises(AppError) as error:
        v2_workflows.update(workflow["workflow_id"], {"name": "Stale"}, 1)
    assert error.value.status == 412
    for sql in ("UPDATE workflow_versions SET version_no=100", "DELETE FROM audit_log"):
        with pytest.raises(DBAPIError) as error, db.begin() as conn:
            conn.execute(text(sql))
        assert error.value.orig.sqlstate == "55000"


def test_queued_cancel_is_terminal_and_idempotent(prepared, db):
    accepted = prepared["start"]()
    run_id = UUID(accepted["data"]["run_id"])
    assert v2_journal.cancel(run_id) == (True, False)
    assert v2_journal.cancel(run_id) == (False, True)
    assert prepared["start"]() == accepted
    with db.connect() as conn:
        assert conn.scalar(text("SELECT status FROM runs")) == "CANCELLED"
        assert conn.scalar(text("SELECT count(*) FROM run_summaries")) == 1
        assert conn.scalar(text("SELECT count(*) FROM spans")) == 0
        assert conn.scalar(text("SELECT last_seq FROM run_executions")) == 3


def test_api_recovery_excludes_v2(prepared, db):
    from app.repositories.execution import fail_running, create_run

    prepared["start"]()
    with db.begin() as conn:
        legacy = create_run(conn, prepared["task"]["task_id"])
        fail_running(conn, "Restarted")
    with db.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT status FROM runs WHERE run_id=:id"),
                {"id": legacy["run_id"]},
            )
            == "FAILED"
        )
        assert (
            conn.scalar(
                text("SELECT r.status FROM runs r JOIN run_executions e USING(run_id)")
            )
            == "RUNNING"
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM run_summaries WHERE execution_mode='LEGACY'")
            )
            == 1
        )
