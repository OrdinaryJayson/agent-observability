from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app.core.errors import AppError
from app.services import v2_journal, v2_runs
from app.worker.recovery import recover_one


def test_expired_owner_is_fenced_and_two_recoverers_compete(prepared, db):
    prepared["start"]()
    original = v2_runs.claim("original")
    with db.begin() as conn:
        conn.execute(
            text(
                "UPDATE run_executions SET lease_expires_at=clock_timestamp()-interval '1 second'"
            )
        )
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(recover_one, ["recovery-a", "recovery-b"]))
    assert sum(row is not None for row in results) == 1
    recovered = next(row for row in results if row)
    assert recovered["lease_epoch"] == 2 and recovered["recovery_count"] == 1
    assert not v2_runs.control(original["run_id"], "original", 1, renew=True)[
        "lease_valid"
    ]
    assert v2_runs.control(original["run_id"], recovered["worker_id"], 2)["lease_valid"]


def test_expired_queue_fails_without_projection(prepared, db):
    prepared["start"]()
    with db.begin() as conn:
        conn.execute(
            text(
                "UPDATE run_executions SET queued_at=clock_timestamp()-interval '301 seconds'"
            )
        )
    assert v2_runs.claim("worker") is None
    assert recover_one("sweeper")["finished"]
    with db.connect() as conn:
        assert conn.scalar(text("SELECT status FROM runs")) == "FAILED"
        assert conn.scalar(text("SELECT error_summary FROM runs")) == "QueueTimeout"
        assert conn.scalar(text("SELECT count(*) FROM run_summaries")) == 1


def test_recovery_budget_and_missing_projection_are_explicit(prepared, db):
    prepared["start"]()
    v2_runs.claim("original")
    for count in range(3):
        with db.begin() as conn:
            conn.execute(
                text(
                    "UPDATE run_executions SET lease_expires_at=clock_timestamp()-interval '1 second'"
                )
            )
        result = recover_one(f"recovery-{count}")
    assert result["finished"]
    with db.connect() as conn:
        assert conn.scalar(text("SELECT recovery_count FROM run_executions")) == 2
        assert conn.scalar(text("SELECT worker_id FROM run_executions")) is None
        assert (
            conn.scalar(
                text(
                    "SELECT payload->>'projection_complete' FROM run_journal WHERE kind='run.finished'"
                )
            )
            == "false"
        )


def test_old_batch_receipt_survives_recovery_but_new_write_does_not(running, db):
    claim, batches, _ = running
    first = v2_journal.commit("worker-a", batches[0])
    with db.begin() as conn:
        conn.execute(
            text(
                "UPDATE run_executions SET lease_expires_at=clock_timestamp()-interval '1 second'"
            )
        )
    recover_one("new-worker")
    assert v2_journal.commit("worker-a", batches[0]) == {**first, "duplicate": True}
    with pytest.raises(AppError) as error:
        v2_journal.commit("worker-a", batches[1])
    assert error.value.code == "LEASE_LOST"
