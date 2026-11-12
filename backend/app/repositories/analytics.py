"""SQL aggregation without multiplying counts by joining one-to-many tables."""

from sqlalchemy import Date, cast, func, select

from app.models.tables import tables
from app.repositories.resources import paged, window


def selected_runs(query):
    runs = tables()["runs"]
    return window(select(runs), runs.c.started_at, query.from_time, query.to_time).cte(
        "selected_runs"
    )


def duration(table, start="start_time", end="end_time"):
    return func.extract("epoch", table.c[end] - table.c[start]) * 1000


def overview(conn, query):
    runs = selected_runs(query)
    elapsed = duration(runs, "started_at", "ended_at")
    result = dict(
        conn.execute(
            select(
                func.count().label("total_runs"),
                func.count().filter(runs.c.status == "SUCCESS").label("success_runs"),
                func.count().filter(runs.c.status == "FAILED").label("failed_runs"),
                func.avg(elapsed).label("avg_duration_ms"),
                func.percentile_cont(0.5)
                .within_group(elapsed)
                .label("p50_duration_ms"),
                func.percentile_cont(0.95)
                .within_group(elapsed)
                .label("p95_duration_ms"),
            ).select_from(runs)
        )
        .mappings()
        .one()
    )
    denominator = result["success_runs"] + result["failed_runs"]
    result["success_rate"] = (
        result["success_runs"] / denominator if denominator else None
    )
    spans = tables()["spans"]
    tokens = (
        conn.execute(
            select(
                func.count().label("total_spans"),
                func.coalesce(
                    func.sum(spans.c.input_tokens).filter(
                        spans.c.operation_type == "LLM"
                    ),
                    0,
                ).label("total_input_tokens"),
                func.coalesce(
                    func.sum(spans.c.output_tokens).filter(
                        spans.c.operation_type == "LLM"
                    ),
                    0,
                ).label("total_output_tokens"),
            ).select_from(spans.join(runs, spans.c.run_id == runs.c.run_id))
        )
        .mappings()
        .one()
    )
    return result | dict(tokens)


def agents(conn, query):
    t = tables()
    spans, agent = t["spans"], t["agents"]
    runs = selected_runs(query)
    source = spans.join(runs, spans.c.run_id == runs.c.run_id)
    counts = (
        select(
            spans.c.agent_id,
            func.count().label("span_count"),
            func.count().filter(spans.c.status == "ERROR").label("error_count"),
            func.avg(duration(spans)).label("avg_duration_ms"),
        )
        .select_from(source)
        .where(spans.c.operation_type == "AGENT", spans.c.agent_id.is_not(None))
        .group_by(spans.c.agent_id)
        .subquery()
    )
    tokens = (
        select(
            spans.c.agent_id,
            func.sum(spans.c.input_tokens).label("total_input_tokens"),
            func.sum(spans.c.output_tokens).label("total_output_tokens"),
        )
        .select_from(source)
        .where(spans.c.operation_type == "LLM")
        .group_by(spans.c.agent_id)
        .subquery()
    )
    statement = (
        select(
            counts.c.agent_id,
            agent.c.name,
            counts.c.span_count,
            counts.c.error_count,
            counts.c.avg_duration_ms,
            func.coalesce(tokens.c.total_input_tokens, 0).label("total_input_tokens"),
            func.coalesce(tokens.c.total_output_tokens, 0).label("total_output_tokens"),
        )
        .select_from(
            counts.join(agent, counts.c.agent_id == agent.c.agent_id).outerjoin(
                tokens, counts.c.agent_id == tokens.c.agent_id
            )
        )
        .order_by(counts.c.span_count.desc(), counts.c.agent_id)
    )
    return paged(conn, statement, query)


def tools(conn, query):
    spans, runs = tables()["spans"], selected_runs(query)
    statement = (
        select(
            spans.c.tool_name,
            func.count().label("span_count"),
            func.count().filter(spans.c.status == "ERROR").label("error_count"),
            func.avg(duration(spans)).label("avg_duration_ms"),
            func.sum(duration(spans)).label("total_duration_ms"),
        )
        .select_from(spans.join(runs, spans.c.run_id == runs.c.run_id))
        .where(spans.c.operation_type == "TOOL")
        .group_by(spans.c.tool_name)
        .order_by(func.count().desc(), spans.c.tool_name.asc().nulls_last())
    )
    return paged(conn, statement, query)


def errors(conn, query):
    spans, runs = tables()["spans"], selected_runs(query)
    statement = (
        select(spans.c.error_type, func.count().label("count"))
        .select_from(spans.join(runs, spans.c.run_id == runs.c.run_id))
        .where(spans.c.status == "ERROR")
        .group_by(spans.c.error_type)
        .order_by(func.count().desc(), spans.c.error_type.asc().nulls_last())
    )
    return paged(conn, statement, query)


def events(conn, query):
    t = tables()
    events, spans, runs = t["span_events"], t["spans"], t["runs"]
    statement = select(
        *events.c, runs.c.trace_id, runs.c.task_id, spans.c.agent_id
    ).select_from(
        events.join(
            spans,
            (events.c.run_id == spans.c.run_id) & (events.c.span_id == spans.c.span_id),
        ).join(runs, spans.c.run_id == runs.c.run_id)
    )
    for key, column in {
        "severity": events.c.severity,
        "task_id": runs.c.task_id,
        "agent_id": spans.c.agent_id,
        "run_id": runs.c.run_id,
        "trace_id": runs.c.trace_id,
        "error_type": spans.c.error_type,
    }.items():
        if (value := getattr(query, key)) is not None:
            statement = statement.where(column == value)
    statement = window(statement, events.c.occurred_at, query.from_time, query.to_time)
    return paged(
        conn, statement.order_by(events.c.occurred_at.desc(), events.c.event_id), query
    )


def trend(conn, query):
    runs = selected_runs(query)
    day = cast(func.timezone("UTC", runs.c.started_at), Date)
    counts = (
        select(
            day.label("date"),
            func.count().label("total_runs"),
            func.count().filter(runs.c.status == "SUCCESS").label("success_runs"),
            func.count().filter(runs.c.status == "FAILED").label("failed_runs"),
        )
        .group_by(day)
        .cte("daily_counts")
    )
    # Return only observed dates; the frontend fills gaps after fetching pages.
    statement = select(counts).order_by(counts.c.date)
    return paged(conn, statement, query)
