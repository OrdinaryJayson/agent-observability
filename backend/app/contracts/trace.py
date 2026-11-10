"""Frozen collected-data types. Owned by project lead, with no service imports."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from app.contracts.base import SpanId, StrictModel


class SpanData(StrictModel):
    span_id: SpanId
    parent_span_id: SpanId | None
    agent_id: UUID | None
    operation_type: Literal["AGENT", "LLM", "TOOL", "RETRIEVAL", "WORKFLOW", "OTHER"]
    span_name: str = Field(min_length=1, max_length=200)
    status: Literal["SUCCESS", "ERROR"]
    start_time: AwareDatetime
    end_time: AwareDatetime
    provider: str | None = Field(max_length=80)
    model_name: str | None = Field(max_length=120)
    tool_name: str | None = Field(max_length=120)
    input_tokens: int | None = Field(ge=0, le=2147483647)
    output_tokens: int | None = Field(ge=0, le=2147483647)
    error_type: str | None = Field(max_length=100)
    error_message: str | None
    attributes: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_values(self):
        if self.end_time < self.start_time:
            raise ValueError("Span ends before it starts")
        if self.operation_type != "LLM" and (
            self.input_tokens is not None or self.output_tokens is not None
        ):
            raise ValueError("Only LLM spans may carry tokens")
        return self


class SpanView(SpanData):
    duration_ms: float


class EventData(StrictModel):
    event_id: UUID
    span_id: SpanId
    event_name: str = Field(min_length=1, max_length=100)
    severity: Literal["TRACE", "DEBUG", "INFO", "WARN", "ERROR"]
    message: str | None
    occurred_at: AwareDatetime
    attributes: dict[str, JsonValue]


@dataclass(frozen=True)
class SimulationResult:
    spans: list[dict]
    events: list[dict]
    final_status: Literal["SUCCESS", "FAILED"]
    error_summary: str | None
