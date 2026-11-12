from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest
from sqlalchemy import event, func, insert, select, update

from app.core.errors import AppError
from app.models.tables import tables
from app.repositories import execution, resources
from app.schemas.api import RunCreate
from app.services import runs
from app.services.run_completion import complete_run
from app.simulator.runner import run_simulation


def test_run_end_time_uses_database_clock_and_never_precedes_start(db):
    with db.begin() as conn:
        task = execution.create_task(conn, {"title": "clock regression"})
        first = execution.create_run(conn, task["task_id"])
        second = execution.create_run(conn, task["task_id"])
        conn.execute(
            update(tables()["runs"]).values(
                started_at=datetime.now(timezone.utc) + timedelta(seconds=10)
            )
        )
    with db.begin() as conn:
        execution.fail_running(conn, "immediate failure", first["run_id"])
    result = run_simulation(
        run_id=str(second["run_id"]),
        trace_id=second["trace_id"],
        config={"min_spans": 1, "max_spans": 1, "failure_rate": 0},
    )
    complete_run(
        run_id=str(second["run_id"]),
        spans=result.spans,
        events=result.events,
        final_status="SUCCESS",
        error_summary=None,
    )
    with db.connect() as conn:
        for run_id, status in [
            (first["run_id"], "FAILED"),
            (second["run_id"], "SUCCESS"),
        ]:
            actual = execution.get_run(conn, run_id)
            assert actual["status"] == status
            assert actual["ended_at"] >= actual["started_at"]


def test_agent_disabled_after_start_does_not_invalidate_completion(db):
    with db.begin() as conn:
        agent = resources.create_agent(conn, {"name": "Snapshot", "role": "research"})
        task = execution.create_task(conn, {"title": "snapshot identity"})
    run = runs.start_run(
        task["task_id"],
        RunCreate(
            simulation_config={
                "agent_count": 1,
                "agent_ids": [agent["agent_id"]],
            }
        ),
    )
    result = run_simulation(
        run_id=str(run["run_id"]),
        trace_id=run["trace_id"],
        config={"min_spans": 3, "max_spans": 3, "failure_rate": 0},
    )
    for span in result.spans:
        if span["operation_type"] != "WORKFLOW":
            span["agent_id"] = agent["agent_id"]
    with db.begin() as conn:
        resources.patch_agent(conn, agent["agent_id"], {"status": "DISABLED"})
    complete_run(
        run_id=str(run["run_id"]),
        spans=result.spans,
        events=result.events,
        final_status="SUCCESS",
        error_summary=None,
    )
    with db.connect() as conn:
        assert execution.get_run(conn, run["run_id"])["status"] == "SUCCESS"


def test_list_count_and_rows_share_snapshot_during_concurrent_insert(client, db):
    client.post("/api/v1/agents", json={"name": "first", "role": "r"})
    inserted = False

    def after_count(conn, cursor, statement, parameters, context, many):
        nonlocal inserted
        if not inserted and "count(" in statement and "FROM agents" in statement:
            inserted = True
            with db.begin() as other:
                other.execute(
                    insert(tables()["agents"]), {"name": "concurrent", "role": "r"}
                )

    event.listen(db, "after_cursor_execute", after_count)
    try:
        response = client.get("/api/v1/agents").json()
    finally:
        event.remove(db, "after_cursor_execute", after_count)
    assert inserted
    assert response["meta"]["total"] == len(response["data"]) == 1
    assert client.get("/api/v1/agents").json()["meta"]["total"] == 2


def test_invalid_trace_rolls_back_all_writes(db):
    with db.begin() as conn:
        task = execution.create_task(conn, {"title": "invalid tree"})
        run = execution.create_run(conn, task["task_id"])
    result = run_simulation(
        run_id=str(run["run_id"]),
        trace_id=run["trace_id"],
        config={"min_spans": 3, "max_spans": 3, "failure_rate": 0},
    )
    result.spans[1]["parent_span_id"] = "f" * 16
    with pytest.raises(AppError) as failure:
        complete_run(
            run_id=str(run["run_id"]),
            spans=result.spans,
            events=result.events,
            final_status="SUCCESS",
            error_summary=None,
        )
    assert failure.value.status == 422
    with db.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(tables()["spans"])) == 0
        assert (
            conn.scalar(select(func.count()).select_from(tables()["span_events"])) == 0
        )
        assert execution.get_run(conn, run["run_id"])["status"] == "RUNNING"


def test_disable_waits_for_agent_validation_transaction(db):
    with db.begin() as conn:
        agent = resources.create_agent(conn, {"name": "locked", "role": "r"})
    attempted, finished = Event(), Event()

    def disable():
        attempted.set()
        with db.begin() as conn:
            resources.patch_agent(conn, agent["agent_id"], {"status": "DISABLED"})
        finished.set()

    with ThreadPoolExecutor(1) as pool:
        with db.begin() as conn:
            resources.validate_agents(conn, [agent["agent_id"]])
            future = pool.submit(disable)
            assert attempted.wait(5)
            assert not finished.wait(0.1)
        future.result(timeout=5)
    assert finished.is_set()
