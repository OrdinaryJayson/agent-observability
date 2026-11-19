from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.query import validate_query_names
from app.api.v2 import envelope
from app.core.database import get_engine, read_snapshot
from app.schemas.v2 import Compare, CursorQuery, Empty, WindowQuery, SeriesQuery
from app.core.errors import AppError
from app.schemas.v1 import TimeWindow
from app.schemas.text import DatabaseText
from app.contracts.v2 import utc
from app.services import v2_analysis, v2_analytics, v2_queries
from pydantic import Field

router = APIRouter(prefix="/api/v2", dependencies=[Depends(validate_query_names)])


@router.get("/analytics/series")
def series(query: Annotated[SeriesQuery, Query()]):
    raise AppError(
        409,
        "FEATURE_NOT_AVAILABLE",
        "Series row fields await the shared response contract",
    )


class AgentQuery(CursorQuery, WindowQuery):
    pass


class AuditQuery(CursorQuery, TimeWindow):
    action: DatabaseText | None = Field(default=None, max_length=80)
    resource_type: DatabaseText | None = Field(default=None, max_length=40)
    resource_id: UUID | None = None


@router.get("/overview")
def overview(query: Annotated[WindowQuery, Query()]):
    with read_snapshot() as conn:
        return envelope(v2_analytics.overview(conn, query))


@router.get("/analytics/aggregate-status")
def aggregate_status():
    with read_snapshot() as conn:
        return envelope(v2_analytics.aggregate_status(conn))


@router.post("/analytics/refresh")
def refresh(body: Empty):
    return envelope(v2_analytics.refresh())


@router.get("/analytics/agents")
def agents(query: Annotated[AgentQuery, Query()]):
    condition, parameters = v2_analytics.window(query)
    sql = f"""WITH selected AS (SELECT r.run_id FROM runs r LEFT JOIN run_executions e USING(run_id) WHERE {condition}),
      counts AS (SELECT agent_id,count(*) AS span_count,count(*) FILTER(WHERE status='ERROR') AS error_count,
        avg(extract(epoch FROM end_time-start_time)*1000) AS avg_duration_ms FROM spans JOIN selected USING(run_id)
        WHERE operation_type='AGENT' AND agent_id IS NOT NULL GROUP BY agent_id),
      tokens AS (SELECT agent_id,coalesce(sum(input_tokens),0) AS total_input_tokens,coalesce(sum(output_tokens),0) AS total_output_tokens
        FROM spans JOIN selected USING(run_id) WHERE operation_type='LLM' GROUP BY agent_id)
      SELECT c.*,a.name,coalesce(t.total_input_tokens,0) AS total_input_tokens,coalesce(t.total_output_tokens,0) AS total_output_tokens
      FROM counts c JOIN agents a USING(agent_id) LEFT JOIN tokens t USING(agent_id)"""
    with get_engine().connect() as conn:
        return v2_queries.cursor_page(
            conn,
            sql,
            parameters,
            query,
            [("span_count", "bigint", int), ("agent_id", "uuid", UUID)],
            "analytics-agents",
        )


@router.get("/runs/{run_id}/analysis")
def analyze(run_id: UUID):
    return envelope(v2_analysis.analyze(run_id))


@router.post("/comparisons")
def compare(body: Compare):
    return envelope(v2_analysis.compare(body.run_ids))


@router.get("/audit")
def audit(query: Annotated[AuditQuery, Query()]):
    conditions = []
    parameters = {}
    for key in ("action", "resource_type", "resource_id"):
        if getattr(query, key) is not None:
            conditions.append(f"{key}=:{key}")
            parameters[key] = getattr(query, key)
    for key, operator in (("from_time", ">="), ("to_time", "<")):
        if getattr(query, key) is not None:
            conditions.append(f"occurred_at{operator}:{key}")
            parameters[key] = getattr(query, key)
    with get_engine().connect() as conn:
        return v2_queries.cursor_page(
            conn,
            "SELECT * FROM audit_log WHERE " + (" AND ".join(conditions) or "TRUE"),
            parameters,
            query,
            [("occurred_at", "timestamptz", utc), ("audit_id", "bigint", int)],
            "audit",
        )
