import copy
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.services import v2_journal


def test_batch_ack_loss_and_terminal_replay(running, db):
    claim, batches, _ = running
    first = v2_journal.commit("worker-a", batches[0])
    assert (first["first_seq"], first["last_seq"]) == (3, 8)
    assert v2_journal.commit("worker-a", batches[0]) == {**first, "duplicate": True}
    final = v2_journal.commit("worker-a", batches[1])
    assert final["last_seq"] == 25 and final["terminal_committed"]
    # Lost ACK can be recovered after ownership was cleared at terminal commit.
    assert v2_journal.commit("old-worker", batches[1]) == {**final, "duplicate": True}
    with db.connect() as conn:
        assert list(
            conn.execute(text("SELECT seq FROM run_journal ORDER BY seq")).scalars()
        ) == list(range(1, 26))
        assert (
            conn.scalar(text("SELECT checkpoint->>'journal_seq' FROM run_executions"))
            == "25"
        )
        assert conn.scalar(text("SELECT count(*) FROM run_summaries")) == 1
        assert conn.scalar(text("SELECT count(*) FROM spans")) == 7
        assert conn.scalar(text("SELECT checkpoint FROM run_executions")) == {
            **batches[1]["checkpoint"],
            "journal_seq": 25,
        }


def test_changed_batch_and_stale_epoch_rejected(running, db):
    claim, batches, _ = running
    v2_journal.commit("worker-a", batches[0])
    changed = copy.deepcopy(batches[0])
    changed["checkpoint"]["logical_time_ms"] += 1
    with pytest.raises(AppError) as error:
        v2_journal.commit("worker-a", changed)
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    with db.begin() as conn:
        conn.execute(text("UPDATE run_executions SET lease_epoch=2"))
    with pytest.raises(AppError) as error:
        v2_journal.commit("worker-a", batches[1])
    assert error.value.code == "LEASE_LOST"


def test_terminal_projection_rolls_back_on_foreign_key_failure(running, db):
    _, batches, closed = running
    v2_journal.commit("worker-a", batches[0])
    # Agent UUID is correctly snapshotted but disappears through privileged DDL
    # outside the application. The deferred projection must still roll back.
    with db.begin() as conn:
        conn.execute(text("DELETE FROM agents"))
    with pytest.raises(IntegrityError):
        v2_journal.commit("worker-a", batches[1])
    with db.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM spans")) == 0
        assert conn.scalar(text("SELECT count(*) FROM run_summaries")) == 0
        assert conn.scalar(text("SELECT last_seq FROM run_executions")) == 8
        assert conn.scalar(text("SELECT status FROM runs")) == "RUNNING"


def test_system_event_advances_watermark_without_duplicate_steps(running):
    claim, batches, _ = running
    v2_journal.cancel(UUID(batches[0]["run_id"]))
    with pytest.raises(AppError) as error:
        v2_journal.commit("worker-a", batches[0])
    assert error.value.code == "CHECKPOINT_CONFLICT"
    assert error.value.details["last_seq"] == 3


def test_completion_cancel_race_rebases_only_control_events(running, db):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.worker.sink import PersistentSink

    claim, batches, _ = running
    v2_journal.commit("worker-a", batches[0])
    barrier = Barrier(2)

    def finish():
        barrier.wait(timeout=5)
        return asyncio.run(
            PersistentSink(claim["run_id"], "worker-a", 1).commit(batches[1])
        )

    def cancel():
        barrier.wait(timeout=5)
        return v2_journal.cancel(claim["run_id"])

    with ThreadPoolExecutor(2) as pool:
        done = pool.submit(finish)
        cancelled = pool.submit(cancel)
        assert done.result(timeout=10).terminal_committed
        cancelled.result(timeout=10)
    with db.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM run_summaries")) == 1
        assert (
            conn.scalar(
                text("SELECT count(*) FROM run_journal WHERE kind='run.finished'")
            )
            == 1
        )
        assert conn.scalar(
            text("SELECT checkpoint->>'journal_seq'=last_seq::text FROM run_executions")
        )


@pytest.mark.parametrize("fault", ["identity", "link_cycle"])
def test_invalid_terminal_identity_or_dependency_rolls_back(running, db, fault):
    _, batches, closed = running
    v2_journal.commit("worker-a", batches[0])
    if fault == "identity":
        closed["spans"][1]["agent_id"] = None
    else:
        link = next(
            link for link in closed["links"] if link["link_type"] == "DEPENDS_ON"
        )
        closed["links"].append(
            {
                "source_span_id": link["target_span_id"],
                "target_span_id": link["source_span_id"],
                "link_type": "DEPENDS_ON",
            }
        )
    with pytest.raises(AppError) as error:
        v2_journal.commit("worker-a", batches[1])
    assert error.value.status == 422
    with db.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM spans")) == 0
        assert conn.scalar(text("SELECT last_seq FROM run_executions")) == 8
