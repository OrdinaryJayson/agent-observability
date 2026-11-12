"""V1 HTTP models; collected-data contracts remain owned by the project lead."""

from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BeforeValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from app.contracts.base import SpanId, StrictModel, TraceId
from app.contracts.trace import EventData
from app.schemas.text import DatabaseText

AgentStatus = Literal["ACTIVE", "DISABLED"]
RunStatus = Literal["RUNNING", "SUCCESS", "FAILED", "CANCELLED"]
SourceType = Literal["SIMULATED", "REAL"]
Severity = Literal["TRACE", "DEBUG", "INFO", "WARN", "ERROR"]
CaseCode = Literal["TRACE_QUERY_INDEX", "ERROR_PARTIAL_INDEX"]
Name = Annotated[DatabaseText, Field(min_length=1, max_length=100, pattern=r"\S")]
Role = Annotated[DatabaseText, Field(min_length=1, max_length=50, pattern=r"\S")]


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Time must include a timezone")
    try:
        return value.astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError("Time is outside the supported UTC range") from exc


def iso_datetime(value):
    if isinstance(value, str) and "T" not in value and "t" not in value:
        raise ValueError("Expected ISO 8601 date and time")
    return value


UTCTime = Annotated[
    datetime, BeforeValidator(iso_datetime), AfterValidator(utc_datetime)
]


class AgentCreate(StrictModel):
    name: Name
    role: Role
    provider: DatabaseText | None = Field(default=None, max_length=80)
    model_name: DatabaseText | None = Field(default=None, max_length=120)


class AgentPatch(StrictModel):
    name: Name = None
    role: Role = None
    provider: DatabaseText | None = Field(default=None, max_length=80)
    model_name: DatabaseText | None = Field(default=None, max_length=120)
    status: AgentStatus = None

    @model_validator(mode="after")
    def supplied_fields(self):
        if not self.model_fields_set:
            raise ValueError("At least one update is required")
        for key in self.model_fields_set & {"name", "role", "status"}:
            if getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class AgentView(AgentCreate):
    agent_id: UUID
    status: AgentStatus
    created_at: datetime


class Pagination(StrictModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class AgentQuery(Pagination):
    status: AgentStatus | None = None


class TraceEventsQuery(Pagination):
    span_id: SpanId | None = None


class RunQuery(Pagination):
    task_id: UUID | None = None
    status: RunStatus | None = None
    source_type: SourceType | None = None
    start_time: UTCTime | None = None
    end_time: UTCTime | None = None

    @model_validator(mode="after")
    def window(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValueError("start_time must precede end_time")
        return self


class TimeWindow(StrictModel):
    # FastAPI 0.115 extracts aliased query fields under their Python names.
    # The route dependency separately rejects non-public parameter names.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_time: UTCTime | None = Field(default=None, alias="from")
    to_time: UTCTime | None = Field(default=None, alias="to")

    @model_validator(mode="after")
    def window(self):
        if self.from_time and self.to_time and self.from_time >= self.to_time:
            raise ValueError("from must precede to")
        return self


class AnalyticsQuery(TimeWindow, Pagination):
    pass


class EventsQuery(AnalyticsQuery):
    severity: Severity | None = None
    task_id: UUID | None = None
    agent_id: UUID | None = None
    run_id: UUID | None = None
    trace_id: TraceId | None = None
    error_type: DatabaseText | None = Field(default=None, max_length=100)


class GlobalEvent(EventData):
    run_id: UUID
    trace_id: TraceId
    task_id: UUID
    agent_id: UUID | None


class Overview(BaseModel):
    total_runs: int
    success_runs: int
    failed_runs: int
    success_rate: float | None
    avg_duration_ms: float | None
    p50_duration_ms: float | None
    p95_duration_ms: float | None
    total_input_tokens: int
    total_output_tokens: int
    total_spans: int


class AgentAnalytics(BaseModel):
    agent_id: UUID
    name: str
    span_count: int
    error_count: int
    avg_duration_ms: float
    total_input_tokens: int
    total_output_tokens: int


class ToolAnalytics(BaseModel):
    tool_name: str | None
    span_count: int
    error_count: int
    avg_duration_ms: float
    total_duration_ms: float


class ErrorAnalytics(BaseModel):
    error_type: str | None
    count: int


class TrendRow(BaseModel):
    date: date
    total_runs: int
    success_runs: int
    failed_runs: int


class BenchmarkRequest(StrictModel):
    case_code: CaseCode
    dataset_size: Literal[1000, 10000, 100000]


class BenchmarkPlan(StrictModel):
    before: dict
    after: dict
    duration_before_ms: float = Field(ge=0)
    duration_after_ms: float = Field(ge=0)
    repeats: Literal[3]


class BenchmarkResult(StrictModel):
    result_id: UUID
    case_code: CaseCode
    dataset_size: Literal[1000, 10000, 100000]
    index_strategy: Literal["no_index_vs_run_start", "no_index_vs_error_partial"]
    duration_ms: float = Field(ge=0)
    plan: BenchmarkPlan
    created_at: UTCTime
