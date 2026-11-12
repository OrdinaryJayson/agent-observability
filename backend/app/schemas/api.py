from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.base import (
    SpanId as SpanId,
    StrictModel as StrictModel,
    TraceId as TraceId,
)
from app.contracts.execution import SimulationConfig as SimulationConfig
from app.schemas.text import DatabaseText

T = TypeVar("T")


class TaskCreate(StrictModel):
    title: DatabaseText = Field(min_length=1, max_length=200, pattern=r"\S")
    description: DatabaseText | None = None
    scenario_type: DatabaseText = Field(default="GENERAL", min_length=1, max_length=50)


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
