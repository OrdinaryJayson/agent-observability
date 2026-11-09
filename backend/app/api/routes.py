from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query

from app.core.database import get_engine
from app.recorder.contracts import EventData, SpanView
from app.repositories import execution
from app.schemas.api import (
    Envelope,
    Page,
    RunAccepted,
    RunCreate,
    RunView,
    SpanId,
    TaskCreate,
    TaskView,
    TraceId,
    TraceView,
)
from app.services import runs

router = APIRouter(prefix="/api/v1")
PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.post("/tasks", status_code=201, response_model=Envelope[TaskView])
def create_task(body: TaskCreate):
    return {"data": runs.create_task(body)}


@router.post(
    "/tasks/{task_id}/runs", status_code=202, response_model=Envelope[RunAccepted]
)
def start_run(task_id: UUID, body: RunCreate, background: BackgroundTasks):
    run = runs.start_run(task_id, body)
    background.add_task(
        runs.execute_run,
        str(run["run_id"]),
        run["trace_id"],
        body.simulation_config.model_dump(),
    )
    return {"data": run, "message": "run accepted"}


@router.get("/runs/{run_id}", response_model=Envelope[RunView])
def get_run(run_id: UUID):
    with get_engine().connect() as conn:
        return {"data": execution.get_run(conn, run_id=run_id)}


@router.get("/traces/{trace_id}", response_model=Envelope[TraceView])
def get_trace(trace_id: TraceId):
    with get_engine().connect() as conn:
        return {"data": execution.trace_overview(conn, trace_id)}


@router.get("/traces/{trace_id}/spans", response_model=Page[SpanView])
def get_spans(trace_id: TraceId, page: PageNumber = 1, page_size: PageSize = 20):
    with get_engine().connect() as conn:
        return execution.trace_items(conn, trace_id, "spans", page, page_size)


@router.get("/traces/{trace_id}/events", response_model=Page[EventData])
def get_events(
    trace_id: TraceId,
    page: PageNumber = 1,
    page_size: PageSize = 20,
    span_id: SpanId | None = None,
):
    with get_engine().connect() as conn:
        return execution.trace_items(
            conn, trace_id, "span_events", page, page_size, span_id
        )
