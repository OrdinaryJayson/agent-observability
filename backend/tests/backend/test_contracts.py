import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute

from app.main import app


def test_all_frozen_examples_have_matching_response_models():
    samples = json.loads(
        (
            Path(__file__).resolve().parents[3] / "contracts/v1-http-examples.json"
        ).read_text(encoding="utf-8")
    )["endpoints"]
    for example in samples:
        route = next(
            r
            for r in app.routes
            if isinstance(r, APIRoute)
            and r.path == example["path"]
            and example["method"] in r.methods
        )
        parsed = route.response_model.model_validate(example["response"])
        output = parsed.model_dump(mode="json")
        expected = example["response"]["data"]
        actual = output["data"]
        if isinstance(expected, list):
            assert len(actual) == len(expected)
            for row, fixture in zip(actual, expected):
                assert row.keys() == fixture.keys()
        else:
            assert actual.keys() == expected.keys()


def test_openapi_exposes_public_parameters_and_error_models():
    schema = app.openapi()
    paths = schema["paths"]
    assert (
        len(
            [
                (p, m)
                for p, ops in paths.items()
                for m in ops
                if p.startswith("/api/v1/")
            ]
        )
        == 21
    )

    def query_names(path):
        return {p["name"] for p in paths[path]["get"].get("parameters", [])}

    assert query_names("/api/v1/analytics/overview") == {"from", "to"}
    assert query_names("/api/v1/analytics/agents") == {
        "from",
        "to",
        "page",
        "page_size",
    }
    assert query_names("/api/v1/events") == {
        "from",
        "to",
        "page",
        "page_size",
        "severity",
        "task_id",
        "agent_id",
        "run_id",
        "trace_id",
        "error_type",
    }
    assert query_names("/api/v1/runs") == {
        "task_id",
        "status",
        "source_type",
        "start_time",
        "end_time",
        "page",
        "page_size",
    }
    assert "504" in paths["/api/v1/benchmarks/run"]["post"]["responses"]
    patch = schema["components"]["schemas"]["AgentPatch"]["properties"]
    assert patch["name"]["type"] == "string"
    assert patch["role"]["type"] == "string"
    assert patch["status"]["type"] == "string"
    assert {v["type"] for v in patch["provider"]["anyOf"]} == {"string", "null"}


@pytest.mark.parametrize(
    "path,params",
    [
        ("/analytics/overview", {"from_time": "2026-01-01T00:00:00Z"}),
        ("/analytics/overview", {"to_time": "2026-01-01T00:00:00Z"}),
        ("/analytics/overview", {"from": "1"}),
        ("/analytics/overview", {"from": "NaN"}),
        ("/events", {"severity": "FATAL"}),
        ("/events", {"error_type": "x" * 101}),
        ("/events", {"trace_id": "A" * 32}),
        ("/events", {"agent_id": "bad"}),
        ("/events", {"start_time": "2026-01-01T00:00:00Z"}),
        ("/tasks", {"search": "test"}),
        ("/agents", {"status": "UNKNOWN"}),
    ],
)
def test_invalid_or_private_query_names_are_rejected(client, path, params):
    response = client.get("/api/v1" + path, params=params)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_trace_filters_and_unknown_query_parameters(client):
    task = client.post("/api/v1/tasks", json={"title": "trace query"}).json()["data"][
        "task_id"
    ]
    accepted = client.post(
        f"/api/v1/tasks/{task}/runs",
        json={
            "simulation_config": {
                "min_spans": 1,
                "max_spans": 1,
                "failure_rate": 0,
            }
        },
    ).json()["data"]
    trace = "/api/v1/traces/" + accepted["trace_id"]
    assert (
        client.get(trace + "/events", params={"span_id": "f" * 16}).json()["data"] == []
    )
    assert client.get(trace + "/events", params={"span_id": "bad"}).status_code == 422
    for path in [
        trace,
        trace + "/events",
        trace + "/spans",
        f"/api/v1/tasks/{task}",
        f"/api/v1/runs/{accepted['run_id']}",
        f"/api/v1/agents/{uuid4()}",
    ]:
        assert client.get(path, params={"unexpected": "x"}).status_code == 422
    assert (
        client.post("/api/v1/tasks?unexpected=x", json={"title": "x"}).status_code
        == 422
    )


def test_nullable_fields_and_empty_groups(client):
    for name in ("agents", "tools", "errors", "trend"):
        assert client.get(f"/api/v1/analytics/{name}").json() == {
            "data": [],
            "meta": {"page": 1, "page_size": 20, "total": 0},
        }
    agent = client.post("/api/v1/agents", json={"name": "n", "role": "r"}).json()[
        "data"
    ]
    assert agent["provider"] is None and agent["model_name"] is None


def test_internal_errors_do_not_leak_details(client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.repositories import resources

    def explode(*args, **kwargs):
        raise RuntimeError("sensitive-database-password")

    monkeypatch.setattr(resources, "list_resources", explode)
    # Existing fixture owns app lifespan/database; this client only sends a request.
    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/tasks")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error",
            "details": {},
        }
    }
    assert "sensitive" not in response.text


def test_far_beyond_last_page_returns_empty_without_database_integer_overflow(
    client, known_data
):
    page = 10**30
    for path in [
        "/agents",
        "/tasks",
        "/runs",
        "/events",
        "/analytics/agents",
        "/analytics/tools",
        "/analytics/errors",
        "/analytics/trend",
        f"/traces/{1:032x}/spans",
        f"/traces/{1:032x}/events",
    ]:
        response = client.get("/api/v1" + path, params={"page": page})
        assert response.status_code == 200, response.text
        assert response.json()["data"] == []
        assert response.json()["meta"]["total"] > 0
