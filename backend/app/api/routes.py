from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.query import validate_query_names

from app.core.database import read_snapshot
from app.contracts.trace import EventData, SpanView
from app.repositories import execution
from app.schemas.api import (
    Envelope,
    Page,
    RunAccepted,
    RunCreate,
    RunView,
    TaskCreate,
    TaskView,
    TraceId,
    TraceView,
)
from app.services import runs
from app.schemas.v1 import Pagination, TraceEventsQuery

router = APIRouter(prefix="/api/v1", dependencies=[Depends(validate_query_names)])


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
        body.simulation_config.model_dump(mode="json"),
    )
    return {"data": run, "message": "run accepted"}


@router.get("/runs/{run_id}", response_model=Envelope[RunView])
def get_run(run_id: UUID):
    with read_snapshot() as conn:
        return {"data": execution.get_run(conn, run_id=run_id)}


@router.get("/traces/{trace_id}", response_model=Envelope[TraceView])
def get_trace(trace_id: TraceId):
    with read_snapshot() as conn:
        return {"data": execution.trace_overview(conn, trace_id)}


@router.get("/traces/{trace_id}/spans", response_model=Page[SpanView])
def get_spans(trace_id: TraceId, query: Annotated[Pagination, Query()]):
    with read_snapshot() as conn:
        return execution.trace_items(
            conn, trace_id, "spans", query.page, query.page_size
        )


@router.get("/traces/{trace_id}/events", response_model=Page[EventData])
def get_events(
    trace_id: TraceId,
    query: Annotated[TraceEventsQuery, Query()],
):
    with read_snapshot() as conn:
        return execution.trace_items(
            conn, trace_id, "span_events", query.page, query.page_size, query.span_id
        )
