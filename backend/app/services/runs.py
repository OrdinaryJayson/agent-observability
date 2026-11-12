import logging

from app.core.database import get_engine
from app.core.errors import AppError
from app.repositories import execution, resources
from app.schemas.api import RunCreate, TaskCreate
from app.services.run_completion import complete_run
from app.simulator import runner

logger = logging.getLogger(__name__)


def create_task(request: TaskCreate):
    with get_engine().begin() as conn:
        return execution.create_task(conn, request.model_dump())


def start_run(task_id, request: RunCreate):
    if request.source_type != "SIMULATED":
        raise AppError(
            409, "FEATURE_NOT_AVAILABLE", "Real model adapter is not enabled"
        )
    with get_engine().begin() as conn:
        resources.get_resource(conn, "tasks", task_id)
        resources.validate_agents(conn, request.simulation_config.agent_ids)
        return execution.create_run(conn, task_id)


def execute_run(run_id: str, trace_id: str, config: dict) -> None:
    try:
        result = runner.run_simulation(run_id=run_id, trace_id=trace_id, config=config)
        complete_run(
            run_id=run_id,
            spans=result.spans,
            events=result.events,
            final_status=result.final_status,
            error_summary=result.error_summary,
        )
    except Exception:
        # Exception text may contain external credentials or SQL parameters; don't log it.
        logger.error("Run %s failed during execution or persistence", run_id)
        try:
            with get_engine().begin() as conn:
                execution.fail_running(
                    conn, "Execution or trace persistence failed", run_id
                )
        except Exception:
            logger.error(
                "Run %s could not be marked failed; startup recovery required", run_id
            )
