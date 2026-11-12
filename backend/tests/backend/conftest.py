from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import insert

from app.models.tables import tables


@pytest.fixture
def known_data(client, db):
    """Fixed database data; repeated Span IDs expose incorrect Event joins."""
    t = tables()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    agent_id, task_id = UUID(int=1), UUID(int=2)
    run_ids = [UUID(int=10 + i) for i in range(5)]
    times = [
        base,
        base + timedelta(days=2),
        base + timedelta(days=2, hours=12),
        base + timedelta(days=3),
        base + timedelta(days=9),
    ]
    statuses = ["SUCCESS", "FAILED", "RUNNING", "CANCELLED", "SUCCESS"]
    durations = [1, 3, None, 5, 100]
    with db.begin() as conn:
        conn.execute(
            insert(t["agents"]),
            {
                "agent_id": agent_id,
                "name": "Research",
                "role": "research",
                "status": "ACTIVE",
            },
        )
        conn.execute(insert(t["tasks"]), {"task_id": task_id, "title": "Known task"})
        for i, run_id in enumerate(run_ids):
            conn.execute(
                insert(t["runs"]),
                {
                    "run_id": run_id,
                    "task_id": task_id,
                    "trace_id": f"{i + 1:032x}",
                    "source_type": "SIMULATED",
                    "status": statuses[i],
                    "started_at": times[i],
                    "ended_at": times[i] + timedelta(seconds=durations[i])
                    if durations[i]
                    else None,
                },
            )
        for i in (0, 1, 4):
            for j, operation in enumerate(("WORKFLOW", "AGENT", "LLM", "TOOL"), 1):
                elapsed = (
                    [1000, 800, 200, 100][j - 1]
                    if i == 0
                    else [3000, 2000, 500, 200][j - 1]
                )
                error = (i == 0 and j == 4) or (i == 1 and j == 2)
                conn.execute(
                    insert(t["spans"]),
                    {
                        "run_id": run_ids[i],
                        "span_id": f"{j:016x}",
                        "parent_span_id": None
                        if j == 1
                        else f"{1 if j == 2 else 2:016x}",
                        "agent_id": None if j == 1 else agent_id,
                        "operation_type": operation,
                        "span_name": operation,
                        "status": "ERROR" if error else "SUCCESS",
                        "start_time": times[i],
                        "end_time": times[i] + timedelta(milliseconds=elapsed),
                        "tool_name": "search" if i == 0 and j == 4 else None,
                        "input_tokens": (10 if i == 0 else 30) if j == 3 else None,
                        "output_tokens": (20 if i == 0 else 40) if j == 3 else None,
                        "error_type": "ToolFailure" if i == 0 and j == 4 else None,
                    },
                )
            conn.execute(
                insert(t["span_events"]),
                {
                    "event_id": UUID(int=100 + i),
                    "run_id": run_ids[i],
                    "span_id": f"{4:016x}",
                    "event_name": "tool.completed",
                    "severity": "ERROR" if i == 0 else "INFO",
                    "message": "known event",
                    "occurred_at": times[i] + timedelta(milliseconds=100),
                },
            )
    return {
        "agent_id": str(agent_id),
        "task_id": str(task_id),
        "run_ids": list(map(str, run_ids)),
        "base": base,
    }
