import ast
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.execution import SimulationConfig
from app.contracts.trace import SimulationResult, SpanData


def test_existing_imports_reexport_identical_frozen_types():
    from app.schemas.api import SimulationConfig as OldConfig
    from app.recorder.contracts import (
        SimulationResult as OldResult,
        SpanData as OldSpan,
    )

    assert OldConfig is SimulationConfig
    assert OldResult is SimulationResult
    assert OldSpan is SpanData


def test_binding_shape_available_without_backend_development():
    config = SimulationConfig(agent_count=1, agent_ids=[uuid4()])
    assert len(config.model_dump(mode="json")["agent_ids"]) == 1
    assert SimulationConfig().agent_ids is None


def test_prototype_does_not_silently_ignore_requested_binding(monkeypatch):
    from app.core.errors import AppError
    from app.schemas.api import RunCreate
    from app.services import runs

    def no_database():
        raise AssertionError("Binding rejection must not access the database")

    monkeypatch.setattr(runs, "get_engine", no_database)
    request = RunCreate(
        simulation_config={"agent_count": 1, "agent_ids": [str(uuid4())]}
    )
    with pytest.raises(AppError) as error:
        runs.start_run(uuid4(), request)
    assert error.value.status == 409
    assert error.value.code == "FEATURE_NOT_AVAILABLE"


@pytest.mark.parametrize("ids", [[str(uuid4())], ["invalid"], []])
def test_binding_length_and_uuid_validation(ids):
    with pytest.raises(ValidationError):
        SimulationConfig(agent_count=3, agent_ids=ids)


def test_duplicate_agents_rejected():
    agent = uuid4()
    with pytest.raises(ValidationError):
        SimulationConfig(agent_count=2, agent_ids=[agent, agent])


def test_shared_models_do_not_import_business_modules():
    root = Path(__file__).resolve().parents[1] / "app/contracts"
    forbidden = (
        "app.schemas",
        "app.services",
        "app.repositories",
        "app.recorder",
        "app.simulator",
    )
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden)


def test_http_examples_preserve_prototype_resource_shapes():
    from app.schemas.api import RunAccepted, RunView, TaskView, TraceView
    from app.contracts.trace import EventData, SpanView

    path = Path(__file__).resolve().parents[2] / "contracts/v1-http-examples.json"
    examples = json.loads(path.read_text(encoding="utf-8"))["endpoints"]
    validators = {
        ("POST", "/api/v1/tasks"): TaskView,
        ("POST", "/api/v1/tasks/{task_id}/runs"): RunAccepted,
        ("GET", "/api/v1/runs/{run_id}"): RunView,
        ("GET", "/api/v1/traces/{trace_id}"): TraceView,
        ("GET", "/api/v1/traces/{trace_id}/spans"): SpanView,
        ("GET", "/api/v1/traces/{trace_id}/events"): EventData,
    }
    for example in examples:
        validator = validators.get((example["method"], example["path"]))
        if validator:
            data = example["response"]["data"]
            validator.model_validate(data[0] if isinstance(data, list) else data)
