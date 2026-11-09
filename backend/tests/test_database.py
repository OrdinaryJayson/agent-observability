from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.core.errors import AppError
from app.models.tables import tables
from app.repositories import execution
from app.services.run_completion import complete_run
from app.simulator.runner import run_simulation


def new_run(db):
    with db.begin() as conn:
        task = execution.create_task(conn, {"title": "transaction test"})
        return execution.create_run(conn, task["task_id"])


def result_for(run):
    return run_simulation(
        run_id=str(run["run_id"]),
        trace_id=run["trace_id"],
        config={"min_spans": 8, "max_spans": 8, "failure_rate": 0},
    )


def finish(run, result):
    complete_run(
        run_id=str(run["run_id"]),
        spans=result.spans,
        events=result.events,
        final_status=result.final_status,
        error_summary=result.error_summary,
    )


def test_migrations_repeat_without_changing_schema(db):
    from app.migrate import migrate

    migrate()
    with db.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM schema_migrations")) == 1


def test_rollback_on_database_constraint_failure(db):
    first = new_run(db)
    result = result_for(first)
    finish(first, result)
    second = new_run(db)
    other = result_for(second)
    other.events[0]["event_id"] = result.events[0]["event_id"]
    with pytest.raises(AppError) as error:
        finish(second, other)
    assert error.value.status == 409
    with db.connect() as conn:
        assert execution.get_run(conn, second["run_id"])["status"] == "RUNNING"
        assert (
            conn.scalar(
                select(func.count())
                .select_from(tables()["spans"])
                .where(tables()["spans"].c.run_id == second["run_id"])
            )
            == 0
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(tables()["span_events"])
                .where(tables()["span_events"].c.run_id == second["run_id"])
            )
            == 0
        )


def test_concurrent_completion_has_single_winner(db):
    run = new_run(db)
    result = result_for(run)
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=10)
        try:
            finish(run, result)
            return "ok"
        except AppError as exc:
            return exc.status

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        outcomes = [f.result(timeout=20) for f in futures]
    assert sorted(outcomes, key=str) == [409, "ok"]
    with db.connect() as conn:
        assert execution.trace_overview(conn, run["trace_id"])["span_count"] == 8


def test_invalid_agent_foreign_key_rolls_back(db):
    run = new_run(db)
    result = result_for(run)
    result.spans[0]["agent_id"] = str(uuid4())
    with pytest.raises(AppError):
        finish(run, result)
    with db.connect() as conn:
        assert execution.trace_overview(conn, run["trace_id"])["span_count"] == 0
