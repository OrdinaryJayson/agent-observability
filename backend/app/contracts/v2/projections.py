"""Projection shapes transcribed from docs/15, with no service dependencies."""

import re
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.contracts.base import SpanId
from app.contracts.trace import EventData, SpanData
from app.contracts.v2 import StrictModel

NodeKey = Annotated[str, Field(pattern=re.compile(r"^(?!sys_)[a-z][a-z0-9_]{0,49}$"))]


class ValidationIssue(StrictModel):
    code: str
    node_key: NodeKey | None
    edge_index: int | None = Field(ge=0)
    # The prose does not narrow path beyond JSON; do not invent a path grammar.
    path: Any
    message: str


class ValidationReport(StrictModel):
    valid: bool
    errors: list[ValidationIssue]


class NodeState(StrictModel):
    node_key: NodeKey
    state: Literal["PENDING", "RUNNING", "SUCCESS", "ERROR", "SKIPPED", "CANCELLED"]
    attempt_no: int = Field(ge=0)
    span_ids: list[SpanId] = Field(max_length=500)


class Link(StrictModel):
    source_span_id: SpanId
    target_span_id: SpanId
    link_type: Literal["DEPENDS_ON", "RETRY_OF", "HANDOFF"]


class SpanOpen(StrictModel):
    span_id: SpanId
    parent_span_id: SpanId | None
    agent_id: UUID | None
    operation_type: Literal["AGENT", "LLM", "TOOL", "RETRIEVAL", "WORKFLOW", "OTHER"]
    span_name: str = Field(min_length=1, max_length=200)
    node_key: NodeKey | None
    role_key: NodeKey | None
    attempt_no: int = Field(ge=1)
    start_time: AwareDatetime
    attributes: dict


class LiveSpan(SpanOpen):
    state: Literal["RUNNING", "SUCCESS", "ERROR"]
    end_time: AwareDatetime | None
    provider: str | None = Field(max_length=80)
    model_name: str | None = Field(max_length=120)
    tool_name: str | None = Field(max_length=120)
    input_tokens: int | None = Field(ge=0, le=2147483647)
    output_tokens: int | None = Field(ge=0, le=2147483647)
    error_type: str | None = Field(max_length=100)
    error_message: str | None


class ClosedProjection(StrictModel):
    spans: list[SpanData] = Field(max_length=500)
    events: list[EventData] = Field(max_length=2000)
    links: list[Link]
    nodes: list[NodeState] = Field(max_length=50)
    final_status: Literal["SUCCESS", "FAILED", "CANCELLED"]
    error_summary: str | None
    time_basis: Literal["REALTIME", "VIRTUAL"]
    logical_duration_ms: float | None = Field(ge=0)


class SnapshotProjection(StrictModel):
    nodes: list[NodeState] = Field(max_length=50)
    spans: list[LiveSpan] = Field(max_length=500)
    events: list[EventData] = Field(max_length=2000)
    links: list[Link]
    closed_result: ClosedProjection | None
