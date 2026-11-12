"""V1 business endpoints. All writes use caller-owned transactions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.query import validate_query_names

from app.core.database import get_engine, read_snapshot
from app.repositories import analytics, resources
from app.schemas.api import Envelope, Page, RunView, TaskView
from app.schemas.v1 import (
    AgentAnalytics,
    AgentCreate,
    AgentPatch,
    AgentQuery,
    AgentView,
    AnalyticsQuery,
    BenchmarkRequest,
    BenchmarkResult,
    ErrorAnalytics,
    EventsQuery,
    GlobalEvent,
    Overview,
    Pagination,
    RunQuery,
    TimeWindow,
    ToolAnalytics,
    TrendRow,
)
from app.services import benchmarks

router = APIRouter(prefix="/api/v1", dependencies=[Depends(validate_query_names)])


@router.post("/agents", status_code=201, response_model=Envelope[AgentView])
def create_agent(body: AgentCreate):
    with get_engine().begin() as conn:
        return {"data": resources.create_agent(conn, body.model_dump())}


@router.get("/agents", response_model=Page[AgentView])
def list_agents(query: Annotated[AgentQuery, Query()]):
    with read_snapshot() as conn:
        return resources.list_resources(conn, "agents", query)


@router.get("/agents/{agent_id}", response_model=Envelope[AgentView])
def get_agent(agent_id: UUID):
    with read_snapshot() as conn:
        return {"data": resources.get_resource(conn, "agents", agent_id)}


@router.patch("/agents/{agent_id}", response_model=Envelope[AgentView])
def patch_agent(agent_id: UUID, body: AgentPatch):
    with get_engine().begin() as conn:
        return {
            "data": resources.patch_agent(
                conn, agent_id, body.model_dump(exclude_unset=True)
            )
        }


@router.get("/tasks", response_model=Page[TaskView])
def list_tasks(query: Annotated[Pagination, Query()]):
    with read_snapshot() as conn:
        return resources.list_resources(conn, "tasks", query)


@router.get("/tasks/{task_id}", response_model=Envelope[TaskView])
def get_task(task_id: UUID):
    with read_snapshot() as conn:
        return {"data": resources.get_resource(conn, "tasks", task_id)}


@router.get("/runs", response_model=Page[RunView])
def list_runs(query: Annotated[RunQuery, Query()]):
    with read_snapshot() as conn:
        return resources.list_runs(conn, query)


@router.get("/events", response_model=Page[GlobalEvent])
def list_events(query: Annotated[EventsQuery, Query()]):
    with read_snapshot() as conn:
        return analytics.events(conn, query)


@router.get("/analytics/overview", response_model=Envelope[Overview])
def overview(query: Annotated[TimeWindow, Query()]):
    with read_snapshot() as conn:
        return {"data": analytics.overview(conn, query)}


@router.get("/analytics/agents", response_model=Page[AgentAnalytics])
def agent_analytics(query: Annotated[AnalyticsQuery, Query()]):
    with read_snapshot() as conn:
        return analytics.agents(conn, query)


@router.get("/analytics/tools", response_model=Page[ToolAnalytics])
def tool_analytics(query: Annotated[AnalyticsQuery, Query()]):
    with read_snapshot() as conn:
        return analytics.tools(conn, query)


@router.get("/analytics/errors", response_model=Page[ErrorAnalytics])
def error_analytics(query: Annotated[AnalyticsQuery, Query()]):
    with read_snapshot() as conn:
        return analytics.errors(conn, query)


@router.get("/analytics/trend", response_model=Page[TrendRow])
def trend(query: Annotated[AnalyticsQuery, Query()]):
    with read_snapshot() as conn:
        return analytics.trend(conn, query)


@router.get("/benchmarks/results", response_model=Page[BenchmarkResult])
def benchmark_results(query: Annotated[Pagination, Query()]):
    return benchmarks.history(query)


@router.post(
    "/benchmarks/run", status_code=201, response_model=Envelope[BenchmarkResult]
)
def run_benchmark(body: BenchmarkRequest):
    return {"data": benchmarks.run(body)}
