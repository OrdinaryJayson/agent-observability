from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TraceId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
SpanId = Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200, pattern=r"\S")
    description: str | None = None
    scenario_type: str = Field(default="GENERAL", min_length=1, max_length=50)


class SimulationConfig(StrictModel):
    scenario: Literal["research"] = "research"
    agent_count: int = Field(default=3, ge=1, le=3)
    min_spans: int = Field(default=8, ge=1, le=500)
    max_spans: int = Field(default=20, ge=1, le=500)
    failure_rate: float = Field(default=0.1, ge=0, le=1)
    seed: int = 42

    @model_validator(mode="after")
    def validate_range(self):
        if self.min_spans > self.max_spans:
            raise ValueError("min_spans must not exceed max_spans")
        return self


class RunCreate(StrictModel):
    source_type: Literal["SIMULATED", "REAL"] = "SIMULATED"
    simulation_config: SimulationConfig = Field(default_factory=SimulationConfig)
    real_config: dict | None = None


class TaskView(TaskCreate):
    task_id: UUID
    created_at: datetime


class RunAccepted(BaseModel):
    run_id: UUID
    trace_id: TraceId
    source_type: Literal["SIMULATED", "REAL"]
    status: Literal["RUNNING", "SUCCESS", "FAILED", "CANCELLED"]


class RunView(RunAccepted):
    task_id: UUID
    started_at: datetime
    ended_at: datetime | None
    error_summary: str | None
    created_at: datetime


class TraceView(BaseModel):
    trace_id: TraceId
    run_id: UUID
    task_id: UUID
    status: Literal["RUNNING", "SUCCESS", "FAILED", "CANCELLED"]
    source_type: Literal["SIMULATED", "REAL"]
    span_count: int
    error_count: int
    started_at: datetime
    ended_at: datetime | None


class Envelope(BaseModel, Generic[T]):
    data: T
    message: str = "success"


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int


class Page(BaseModel, Generic[T]):
    data: list[T]
    meta: PageMeta


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
