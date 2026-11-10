from uuid import uuid4

import pytest


def launch(client, config=None):
    task = client.post("/api/v1/tasks", json={"title": "API integration"})
    assert task.status_code == 201
    run = client.post(
        f"/api/v1/tasks/{task.json()['data']['task_id']}/runs",
        json={
            "simulation_config": config or {"failure_rate": 0},
        },
    )
    assert run.status_code == 202
    assert run.json()["data"]["status"] == "RUNNING"
    return run.json()["data"]


@pytest.mark.parametrize("failure_rate, expected", [(0, "SUCCESS"), (1, "FAILED")])
def test_round_trip_and_pagination(client, failure_rate, expected):
    accepted = launch(
        client, {"failure_rate": failure_rate, "min_spans": 105, "max_spans": 105}
    )
    run = client.get(f"/api/v1/runs/{accepted['run_id']}").json()["data"]
    assert run["status"] == expected
    assert run["ended_at"].endswith("Z")
    path = f"/api/v1/traces/{accepted['trace_id']}"
    assert client.get(path).json()["data"]["span_count"] == 105
    first = client.get(path + "/spans?page_size=100").json()
    second = client.get(path + "/spans?page=2&page_size=100").json()
    assert len(first["data"]) == 100
    assert len(second["data"]) == 5
    assert first["meta"]["total"] == 105
    assert len({s["span_id"] for s in first["data"] + second["data"]}) == 105
    assert "span_pk" not in first["data"][0]
    events = client.get(path + "/events?page_size=100").json()
    assert events["meta"]["total"] >= 2
    span_id = events["data"][0]["span_id"]
    filtered = client.get(path + f"/events?span_id={span_id}").json()
    assert all(e["span_id"] == span_id for e in filtered["data"])


def test_background_exception_marks_run_failed(client, monkeypatch):
    from app.simulator import runner

    def explode(**kwargs):
        raise RuntimeError("never expose this secret")

    monkeypatch.setattr(runner, "run_simulation", explode)
    accepted = launch(client)
    run = client.get(f"/api/v1/runs/{accepted['run_id']}").json()["data"]
    assert run["status"] == "FAILED"
    assert "secret" not in run["error_summary"]
    assert (
        client.get(f"/api/v1/traces/{accepted['trace_id']}").json()["data"][
            "span_count"
        ]
        == 0
    )


def test_restart_recovers_unfinished_runs(db):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.repositories import execution

    with db.begin() as conn:
        task = execution.create_task(conn, {"title": "unfinished"})
        run = execution.create_run(conn, task["task_id"])
    with TestClient(app) as client:
        actual = client.get(f"/api/v1/runs/{run['run_id']}").json()["data"]
        assert actual["status"] == "FAILED"
        assert actual["ended_at"] is not None
        assert actual["error_summary"] == "Backend restarted before trace persistence"


def test_errors_and_openapi(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/runs/invalid").status_code == 422
    assert client.get(f"/api/v1/runs/{uuid4()}").status_code == 404
    assert client.get("/api/v1/traces/" + "a" * 32).status_code == 404
    assert client.post("/api/v1/tasks", json={"title": "  "}).status_code == 422
    task = client.post("/api/v1/tasks", json={"title": "check"}).json()["data"][
        "task_id"
    ]
    for body in [
        {"simulation_config": {"min_spans": 5, "max_spans": 2}},
        {"simulation_config": {"failure_rate": 2}},
        {"api_key": "secret"},
    ]:
        response = client.post(f"/api/v1/tasks/{task}/runs", json=body)
        assert response.status_code == 422
        assert "error" in response.json()
        assert "secret" not in response.text
    assert (
        client.post(
            f"/api/v1/tasks/{task}/runs", json={"source_type": "REAL"}
        ).status_code
        == 409
    )
    accepted = launch(client)
    assert (
        client.get(
            f"/api/v1/traces/{accepted['trace_id']}/spans?page_size=101"
        ).status_code
        == 422
    )
    schema = client.get("/openapi.json").json()
    assert {
        "/health",
        "/api/v1/tasks",
        "/api/v1/tasks/{task_id}/runs",
        "/api/v1/runs/{run_id}",
        "/api/v1/traces/{trace_id}",
        "/api/v1/traces/{trace_id}/spans",
        "/api/v1/traces/{trace_id}/events",
    } <= schema["paths"].keys()
    assert "SpanView" in schema["components"]["schemas"]
