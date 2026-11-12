"""Resource queries and binding validation within caller-owned transactions."""

from sqlalchemy import func, insert, select, update

from app.core.errors import AppError, not_found
from app.models.tables import tables


def paged(conn, statement, query):
    total = conn.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    )
    offset = (query.page - 1) * query.page_size
    rows = (
        conn.execute(statement.offset(offset).limit(query.page_size)).mappings().all()
        if offset < total
        else []
    )
    return {
        "data": [dict(row) for row in rows],
        "meta": {"page": query.page, "page_size": query.page_size, "total": total},
    }


def get_resource(conn, kind, resource_id):
    table = tables()[kind]
    key = table.c.agent_id if kind == "agents" else table.c.task_id
    row = conn.execute(select(table).where(key == resource_id)).mappings().one_or_none()
    if row is None:
        raise not_found()
    return dict(row)


def create_agent(conn, values):
    table = tables()["agents"]
    return dict(
        conn.execute(insert(table).values(**values).returning(table)).mappings().one()
    )


def patch_agent(conn, agent_id, values):
    table = tables()["agents"]
    row = (
        conn.execute(
            update(table)
            .where(table.c.agent_id == agent_id)
            .values(**values)
            .returning(table)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise not_found()
    return dict(row)


def list_resources(conn, kind, query):
    table = tables()[kind]
    key = table.c.agent_id if kind == "agents" else table.c.task_id
    statement = select(table)
    if kind == "agents" and query.status is not None:
        statement = statement.where(table.c.status == query.status)
    return paged(conn, statement.order_by(table.c.created_at.desc(), key), query)


def window(statement, column, start, end):
    if start is not None:
        statement = statement.where(column >= start)
    if end is not None:
        statement = statement.where(column < end)
    return statement


def list_runs(conn, query):
    table = tables()["runs"]
    statement = select(table)
    for key in ("task_id", "status", "source_type"):
        if (value := getattr(query, key)) is not None:
            statement = statement.where(table.c[key] == value)
    statement = window(statement, table.c.started_at, query.start_time, query.end_time)
    return paged(
        conn, statement.order_by(table.c.started_at.desc(), table.c.run_id), query
    )


def validate_agents(conn, agent_ids):
    if agent_ids is None:
        return
    table = tables()["agents"]
    # Hold shared row locks until the Run is created: PATCH must wait, so the
    # accepted identity/status is a consistent snapshot at Run creation.
    rows = conn.execute(
        select(table.c.agent_id, table.c.status)
        .where(table.c.agent_id.in_(agent_ids))
        .order_by(table.c.agent_id)
        .with_for_update(read=True)
    ).all()
    if len(rows) != len(agent_ids):
        raise not_found()
    if any(row.status != "ACTIVE" for row in rows):
        raise AppError(409, "CONFLICT", "All selected agents must be ACTIVE")
