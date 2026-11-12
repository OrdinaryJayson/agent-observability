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


def test_binding_is_validated_and_persisted_end_to_end(client):
    from uuid import uuid4

    agent = client.post("/api/v1/agents", json={"name": "Trace", "role": "researcher"})
    assert agent.status_code == 201
    agent_id = agent.json()["data"]["agent_id"]
    task = client.post("/api/v1/tasks", json={"title": "binding contract"}).json()[
        "data"
    ]
    path = f"/api/v1/tasks/{task['task_id']}/runs"
    config = {
        "agent_count": 1,
        "agent_ids": [agent_id],
        "min_spans": 8,
        "max_spans": 8,
        "failure_rate": 0,
    }
    missing = client.post(
        path, json={"simulation_config": {**config, "agent_ids": [str(uuid4())]}}
    )
    assert missing.status_code == 404
    response = client.post(path, json={"simulation_config": config})
    assert response.status_code == 202, response.text
    run = client.get(f"/api/v1/runs/{response.json()['data']['run_id']}").json()["data"]
    assert run["status"] == "SUCCESS"
    trace = run["trace_id"]
    spans = client.get(f"/api/v1/traces/{trace}/spans?page_size=100").json()["data"]
    assert any(
        s["operation_type"] == "AGENT" and s["agent_id"] == agent_id for s in spans
    )
    assert any(
        s["operation_type"] == "LLM" and s["agent_id"] == agent_id for s in spans
    )
    assert all(
        s["agent_id"] is None for s in spans if s["operation_type"] == "WORKFLOW"
    )
    stats = client.get("/api/v1/analytics/agents").json()["data"]
    assert any(
        row["agent_id"] == agent_id and row["total_input_tokens"] > 0 for row in stats
    )
    assert (
        client.patch(
            f"/api/v1/agents/{agent_id}", json={"status": "DISABLED"}
        ).status_code
        == 200
    )
    disabled = client.post(path, json={"simulation_config": config})
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "CONFLICT"


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
