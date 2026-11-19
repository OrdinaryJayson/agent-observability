"""Bound parameters and stable cursors for persisted trace search."""

import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import Field, field_validator

from app.api.query import validate_query_names
from app.contracts.base import TraceId
from app.contracts.v2 import safe_json, utc
from app.core.database import get_engine
from app.schemas.text import DatabaseText
from app.schemas.v1 import Severity, TimeWindow
from app.schemas.v2 import CursorQuery
from app.services.v2_queries import cursor_page

router = APIRouter(
    prefix="/api/v2/search", dependencies=[Depends(validate_query_names)]
)


class SpanQuery(CursorQuery, TimeWindow):
    task_id: UUID | None = None
    run_id: UUID | None = None
    agent_id: UUID | None = None
    status: Literal["SUCCESS", "ERROR"] | None = None
    type: Literal["AGENT", "LLM", "TOOL", "RETRIEVAL", "WORKFLOW", "OTHER"] | None = (
        None
    )
    error_type: DatabaseText | None = Field(default=None, max_length=100)
    attributes: str | None = None
    q: DatabaseText | None = Field(default=None, max_length=200)

    @field_validator("attributes")
    @classmethod
    def json_object(cls, value):
        if value is not None:
            if len(value.encode("utf-8")) > 2048:
                raise ValueError("Attributes exceeds 2 KiB")
            parsed = safe_json(json.loads(value))
            if not isinstance(parsed, dict):
                raise ValueError("Attributes must be a JSON object")
            return json.dumps(
                parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        return value


class EventQuery(CursorQuery, TimeWindow):
    task_id: UUID | None = None
    run_id: UUID | None = None
    agent_id: UUID | None = None
    trace_id: TraceId | None = None
    severity: Severity | None = None
    error_type: DatabaseText | None = Field(default=None, max_length=100)
    mode: Literal["REALTIME", "VIRTUAL", "LEGACY"] | None = None


def filters(query, mapping, time_column):
    conditions, parameters = [], {}
    for key, column in mapping.items():
        value = getattr(query, key)
        if value is not None:
            conditions.append(f"{column}=:{key}")
            parameters[key] = value
    for key, operator in (("from_time", ">="), ("to_time", "<")):
        value = getattr(query, key)
        if value is not None:
            conditions.append(f"{time_column}{operator}:{key}")
            parameters[key] = value
    return conditions, parameters


@router.get("/spans")
def spans(query: Annotated[SpanQuery, Query()]):
    conditions, parameters = filters(
        query,
        {
            "task_id": "r.task_id",
            "run_id": "s.run_id",
            "agent_id": "s.agent_id",
            "status": "s.status",
            "type": "s.operation_type",
            "error_type": "s.error_type",
        },
        "s.start_time",
    )
    if query.attributes is not None:
        conditions.append("s.attributes @> CAST(:attributes AS jsonb)")
        parameters["attributes"] = query.attributes
    if query.q is not None:
        conditions.append(
            "to_tsvector('simple',coalesce(s.error_message,'')) @@ plainto_tsquery('simple',:q)"
        )
        parameters["q"] = query.q
    sql = (
        "SELECT s.*,r.task_id,r.trace_id FROM spans s JOIN runs r USING(run_id) WHERE "
        + (" AND ".join(conditions) or "TRUE")
    )
    with get_engine().connect() as conn:
        result = cursor_page(
            conn,
            sql,
            parameters,
            query,
            [("start_time", "timestamptz", utc), ("span_pk", "bigint", int)],
            "search-spans",
        )
        for row in result["data"]:
            row.pop("span_pk")
        return result


@router.get("/events")
def events(query: Annotated[EventQuery, Query()]):
    conditions, parameters = filters(
        query,
        {
            "task_id": "r.task_id",
            "run_id": "e.run_id",
            "agent_id": "s.agent_id",
            "trace_id": "r.trace_id",
            "severity": "e.severity",
            "error_type": "s.error_type",
            "mode": "coalesce(x.config->>'mode','LEGACY')",
        },
        "e.occurred_at",
    )
    sql = """SELECT e.*,r.task_id,r.trace_id,s.agent_id FROM span_events e
      JOIN spans s USING(run_id,span_id) JOIN runs r USING(run_id)
      LEFT JOIN run_executions x USING(run_id) WHERE """ + (
        " AND ".join(conditions) or "TRUE"
    )
    with get_engine().connect() as conn:
        return cursor_page(
            conn,
            sql,
            parameters,
            query,
            [("occurred_at", "timestamptz", utc), ("event_id", "uuid", UUID)],
            "search-events",
        )
