"""Database access stays here; callers own transaction boundaries."""

import secrets
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, insert, select, update

from app.core.errors import not_found
from app.models.tables import tables


def create_task(conn, values: dict) -> dict:
    table = tables()["tasks"]
    return dict(
        conn.execute(insert(table).values(**values).returning(table)).mappings().one()
    )


def create_run(conn, task_id) -> dict:
    t = tables()
    if not conn.scalar(
        select(t["tasks"].c.task_id).where(t["tasks"].c.task_id == task_id)
    ):
        raise not_found()
    table = t["runs"]
    return dict(
        conn.execute(
            insert(table)
            .values(
                run_id=uuid4(),
                task_id=task_id,
                trace_id=secrets.token_hex(16),
                source_type="SIMULATED",
                status="RUNNING",
            )
            .returning(table)
        )
        .mappings()
        .one()
    )


def get_run(conn, run_id=None, trace_id=None, *, lock=False) -> dict:
    table = tables()["runs"]
    query = (
        select(table).where(table.c.run_id == run_id)
        if run_id is not None
        else select(table).where(table.c.trace_id == trace_id)
    )
    row = (
        conn.execute(query.with_for_update() if lock else query)
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise not_found()
    return dict(row)


def trace_overview(conn, trace_id: str) -> dict:
    run = get_run(conn, trace_id=trace_id)
    s = tables()["spans"]
    counts = conn.execute(
        select(func.count(), func.count().filter(s.c.status == "ERROR")).where(
            s.c.run_id == run["run_id"]
        )
    ).one()
    return {
        k: run[k]
        for k in [
            "trace_id",
            "run_id",
            "task_id",
            "status",
            "source_type",
            "started_at",
            "ended_at",
        ]
    } | {
        "span_count": counts[0],
        "error_count": counts[1],
    }


def trace_items(
    conn,
    trace_id: str,
    kind: str,
    page: int,
    page_size: int,
    span_id: str | None = None,
) -> dict:
    run = get_run(conn, trace_id=trace_id)
    table = tables()[kind]
    condition = table.c.run_id == run["run_id"]
    if span_id is not None:
        condition &= table.c.span_id == span_id
    total = conn.scalar(select(func.count()).select_from(table).where(condition))
    is_span = kind == "spans"
    columns = [col for col in table.c if col.name not in {"run_id", "span_pk"}]
    ordering = (
        (table.c.start_time, table.c.span_id)
        if is_span
        else (table.c.occurred_at, table.c.event_id)
    )
    rows = [
        dict(row)
        for row in conn.execute(
            select(*columns)
            .where(condition)
            .order_by(*ordering)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).mappings()
    ]
    if is_span:
        for row in rows:
            row["duration_ms"] = (
                row["end_time"] - row["start_time"]
            ).total_seconds() * 1000
    return {
        "data": rows,
        "meta": {"page": page, "page_size": page_size, "total": total},
    }


def save_result(conn, run_id, spans, events, final_status, error_summary):
    t = tables()
    conn.execute(insert(t["spans"]), [{**s, "run_id": run_id} for s in spans])
    if events:
        conn.execute(
            insert(t["span_events"]), [{**e, "run_id": run_id} for e in events]
        )
    conn.execute(
        update(t["runs"])
        .where(t["runs"].c.run_id == run_id)
        .values(
            status=final_status,
            ended_at=datetime.now(timezone.utc),
            error_summary=error_summary,
        )
    )


def fail_running(conn, summary: str, run_id=None):
    table = tables()["runs"]
    condition = table.c.status == "RUNNING"
    if run_id is not None:
        condition &= table.c.run_id == run_id
    conn.execute(
        update(table)
        .where(condition)
        .values(
            status="FAILED",
            ended_at=datetime.now(timezone.utc),
            error_summary=summary,
        )
    )
