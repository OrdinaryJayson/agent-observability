from uuid import uuid4
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.tables import tables


def new_agent(client, **values):
    response = client.post(
        "/api/v1/agents", json={"name": "Research", "role": "research", **values}
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def new_task(client):
    return client.post("/api/v1/tasks", json={"title": "Task"}).json()["data"][
        "task_id"
    ]


def test_agent_lifecycle_and_partial_update(client):
    agent = new_agent(client, provider="mock", model_name="model")
    path = f"/api/v1/agents/{agent['agent_id']}"
    assert agent["status"] == "ACTIVE"
    assert client.get(path).json()["data"] == agent
    patched = client.patch(path, json={"provider": None, "status": "DISABLED"})
    assert patched.status_code == 200
    assert patched.json()["data"] == {**agent, "provider": None, "status": "DISABLED"}
    assert client.get("/api/v1/agents?status=ACTIVE").json()["meta"]["total"] == 0
    assert (
        client.get("/api/v1/agents?status=DISABLED").json()["data"][0]["agent_id"]
        == agent["agent_id"]
    )
    assert client.patch(path, json={"status": "ACTIVE"}).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": None},
        {"role": None},
        {"status": None},
        {"name": "  "},
        {"role": "\t"},
        {"name": "x" * 101},
        {"role": "x" * 51},
        {"provider": "x" * 81},
        {"model_name": "x" * 121},
        {"status": "DELETED"},
        {"extra": "secret"},
    ],
)
def test_agent_patch_validation(client, body):
    agent = new_agent(client)
    response = client.patch(f"/api/v1/agents/{agent['agent_id']}", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"name": "a"},
        {"name": "a", "role": ""},
        {"name": "a", "role": "r", "status": "ACTIVE"},
    ],
)
def test_agent_create_validation(client, body):
    assert client.post("/api/v1/agents", json=body).status_code == 422


def test_resource_lists_and_missing_resources(client):
    agents = [new_agent(client, name=str(i)) for i in range(3)]
    first = client.get("/api/v1/agents?page_size=2").json()
    second = client.get("/api/v1/agents?page=2&page_size=2").json()
    assert first["meta"] == {"page": 1, "page_size": 2, "total": 3}
    assert {r["agent_id"] for r in first["data"] + second["data"]} == {
        a["agent_id"] for a in agents
    }
    beyond = client.get("/api/v1/agents?page=100").json()
    assert beyond["data"] == [] and beyond["meta"]["total"] == 3
    task = new_task(client)
    assert client.get(f"/api/v1/tasks/{task}").json()["data"]["title"] == "Task"
    assert client.get("/api/v1/tasks").json()["meta"]["total"] == 1
    for kind in ("agents", "tasks"):
        assert client.get(f"/api/v1/{kind}/{uuid4()}").status_code == 404
        assert client.get(f"/api/v1/{kind}/invalid").status_code == 422
    assert (
        client.patch(f"/api/v1/agents/{uuid4()}", json={"name": "x"}).status_code == 404
    )


def test_binding_validation_happens_before_run_creation(client, db):
    agent, task = new_agent(client), new_task(client)
    path = f"/api/v1/tasks/{task}/runs"
    config = {"agent_count": 1, "agent_ids": [agent["agent_id"]]}
    client.patch(f"/api/v1/agents/{agent['agent_id']}", json={"status": "DISABLED"})
    assert client.post(path, json={"simulation_config": config}).status_code == 409
    assert (
        client.post(
            path, json={"simulation_config": {**config, "agent_ids": [str(uuid4())]}}
        ).status_code
        == 404
    )
    for ids in ([], ["bad"], [agent["agent_id"], agent["agent_id"]]):
        assert (
            client.post(
                path, json={"simulation_config": {**config, "agent_ids": ids}}
            ).status_code
            == 422
        )
    with db.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(tables()["runs"])) == 0


def test_binding_passes_json_ids_and_multiple_runs(client, monkeypatch):
    from app.simulator import runner

    original = runner.run_simulation
    seen = []

    def capture(**kwargs):
        seen.append(kwargs["config"])
        # Prototype is only a test stand-in; C owns actual identity inheritance.
        return original(**kwargs)

    monkeypatch.setattr(runner, "run_simulation", capture)
    agent, task = new_agent(client), new_task(client)
    path = f"/api/v1/tasks/{task}/runs"
    for _ in range(2):
        response = client.post(
            path,
            json={
                "simulation_config": {
                    "agent_count": 1,
                    "agent_ids": [agent["agent_id"]],
                    "failure_rate": 0,
                }
            },
        )
        assert response.status_code == 202, response.text
        assert (
            client.get(f"/api/v1/runs/{response.json()['data']['run_id']}").json()[
                "data"
            ]["status"]
            == "SUCCESS"
        )
    assert all(c["agent_ids"] == [agent["agent_id"]] for c in seen)
    listing = client.get(
        "/api/v1/runs", params={"task_id": task, "status": "SUCCESS"}
    ).json()
    assert listing["meta"]["total"] == 2
    assert len({r["run_id"] for r in listing["data"]}) == 2


@pytest.mark.parametrize(
    "path",
    [
        "/agents",
        "/tasks",
        "/runs",
        "/events",
        "/analytics/agents",
        "/analytics/tools",
        "/analytics/errors",
        "/analytics/trend",
        "/benchmarks/results",
    ],
)
@pytest.mark.parametrize(
    "params", [{"page": 0}, {"page_size": 101}, {"unknown": "value"}]
)
def test_query_validation(client, path, params):
    response = client.get("/api/v1" + path, params=params)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "params",
    [
        {"start_time": "2026-01-01T00:00:00"},
        {"start_time": "2026-01-02T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"},
        {"status": "ERROR"},
        {"source_type": "invalid"},
        {"task_id": "bad"},
    ],
)
def test_run_filter_validation(client, params):
    assert client.get("/api/v1/runs", params=params).status_code == 422


def test_fixed_bound_result_persists_and_reconciles_logs_and_statistics(
    client, monkeypatch
):
    from app.contracts.trace import SimulationResult
    from app.simulator import runner

    def fixed_result(*, run_id, trace_id, config):
        assert isinstance(config["agent_ids"][0], str)
        now = datetime.now(timezone.utc)
        spans = []
        for index, kind in enumerate(["WORKFLOW", "AGENT", "LLM", "TOOL"], 1):
            spans.append(
                {
                    "span_id": f"{index:016x}",
                    "parent_span_id": None
                    if index == 1
                    else f"{1 if index == 2 else 2:016x}",
                    "agent_id": None if index == 1 else config["agent_ids"][0],
                    "operation_type": kind,
                    "span_name": kind,
                    "status": "ERROR" if index == 4 else "SUCCESS",
                    "start_time": now - timedelta(milliseconds=100),
                    "end_time": now,
                    "provider": None,
                    "model_name": None,
                    "tool_name": "fixed_search" if index == 4 else None,
                    "input_tokens": 10 if index == 3 else None,
                    "output_tokens": 5 if index == 3 else None,
                    "error_type": "RecoveredError" if index == 4 else None,
                    "error_message": None,
                    "attributes": {},
                }
            )
        events = [
            {
                "event_id": str(uuid4()),
                "span_id": f"{4:016x}",
                "event_name": "tool.failed",
                "severity": "ERROR",
                "message": "recovered",
                "occurred_at": now,
                "attributes": {},
            }
        ]
        return SimulationResult(
            spans=spans, events=events, final_status="SUCCESS", error_summary=None
        )

    monkeypatch.setattr(runner, "run_simulation", fixed_result)
    agent, task = new_agent(client), new_task(client)
    response = client.post(
        f"/api/v1/tasks/{task}/runs",
        json={
            "simulation_config": {
                "agent_count": 1,
                "agent_ids": [agent["agent_id"]],
                "min_spans": 4,
                "max_spans": 4,
            }
        },
    )
    assert response.status_code == 202
    run = response.json()["data"]
    trace = client.get(f"/api/v1/traces/{run['trace_id']}").json()["data"]
    assert (
        trace["status"] == "SUCCESS"
        and trace["span_count"] == 4
        and trace["error_count"] == 1
    )
    events = client.get(
        "/api/v1/events", params={"agent_id": agent["agent_id"]}
    ).json()["data"]
    assert len(events) == 1 and events[0]["run_id"] == run["run_id"]
    overview = client.get("/api/v1/analytics/overview").json()["data"]
    assert overview["success_runs"] == 1 and overview["failed_runs"] == 0
    assert overview["total_input_tokens"] == 10 and overview["total_output_tokens"] == 5
    groups = client.get("/api/v1/analytics/agents").json()["data"]
    assert groups[0]["span_count"] == 1 and groups[0]["total_input_tokens"] == 10
    assert groups[0]["avg_duration_ms"] == 100
