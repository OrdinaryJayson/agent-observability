import pytest


WINDOW = {"from": "2026-01-01T00:00:00Z", "to": "2026-01-05T00:00:00Z"}


def test_overview_exact_counts_and_quantiles(client, known_data):
    response = client.get("/api/v1/analytics/overview", params=WINDOW)
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "total_runs": 4,
        "success_runs": 1,
        "failed_runs": 1,
        "success_rate": 0.5,
        "avg_duration_ms": 3000,
        "p50_duration_ms": 3000,
        "p95_duration_ms": 4800,
        "total_input_tokens": 40,
        "total_output_tokens": 60,
        "total_spans": 8,
    }


def test_empty_overview(client):
    data = client.get("/api/v1/analytics/overview").json()["data"]
    assert data == {
        "total_runs": 0,
        "success_runs": 0,
        "failed_runs": 0,
        "success_rate": None,
        "avg_duration_ms": None,
        "p50_duration_ms": None,
        "p95_duration_ms": None,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_spans": 0,
    }


def test_grouped_analytics_do_not_double_count_children(client, known_data):
    agents = client.get("/api/v1/analytics/agents", params=WINDOW).json()
    assert agents["data"] == [
        {
            "agent_id": known_data["agent_id"],
            "name": "Research",
            "span_count": 2,
            "error_count": 1,
            "avg_duration_ms": 1400,
            "total_input_tokens": 40,
            "total_output_tokens": 60,
        }
    ]
    tools = client.get("/api/v1/analytics/tools", params=WINDOW).json()["data"]
    assert tools == [
        {
            "tool_name": "search",
            "span_count": 1,
            "error_count": 1,
            "avg_duration_ms": 100,
            "total_duration_ms": 100,
        },
        {
            "tool_name": None,
            "span_count": 1,
            "error_count": 0,
            "avg_duration_ms": 200,
            "total_duration_ms": 200,
        },
    ]
    errors = client.get("/api/v1/analytics/errors", params=WINDOW).json()["data"]
    assert errors == [
        {"error_type": "ToolFailure", "count": 1},
        {"error_type": None, "count": 1},
    ]


def test_trend_utc_dates_gaps_and_pagination(client, known_data):
    first = client.get("/api/v1/analytics/trend", params={**WINDOW, "page_size": 2})
    assert first.status_code == 200, first.text
    assert first.json() == {
        "data": [
            {
                "date": "2026-01-01",
                "total_runs": 1,
                "success_runs": 1,
                "failed_runs": 0,
            },
            {
                "date": "2026-01-03",
                "total_runs": 2,
                "success_runs": 0,
                "failed_runs": 1,
            },
        ],
        "meta": {"page": 1, "page_size": 2, "total": 3},
    }
    second = client.get(
        "/api/v1/analytics/trend", params={**WINDOW, "page_size": 2, "page": 2}
    ).json()
    assert second["data"] == [
        {"date": "2026-01-04", "total_runs": 1, "success_runs": 0, "failed_runs": 0}
    ]
    assert second["meta"]["total"] == 3


def test_empty_trend(client):
    assert client.get("/api/v1/analytics/trend").json()["data"] == []
    data = client.get("/api/v1/analytics/trend", params=WINDOW).json()
    assert data["meta"]["total"] == 0
    assert data["data"] == []


def test_event_filters_join_by_run_and_span(client, known_data):
    response = client.get("/api/v1/events", params=WINDOW)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["meta"]["total"] == 2
    assert [e["run_id"] for e in data["data"]] == known_data["run_ids"][1::-1]
    filters = {
        "agent_id": known_data["agent_id"],
        "task_id": known_data["task_id"],
        "run_id": known_data["run_ids"][0],
        "trace_id": f"{1:032x}",
        "error_type": "ToolFailure",
        "severity": "ERROR",
        **WINDOW,
    }
    filtered = client.get("/api/v1/events", params=filters).json()
    assert filtered["meta"]["total"] == 1
    assert filtered["data"][0]["span_id"] == f"{4:016x}"
    assert (
        client.get("/api/v1/events", params={"trace_id": "a" * 32}).json()["data"] == []
    )
    assert (
        client.get("/api/v1/events", params={"to": "2026-01-01T00:00:00.100Z"}).json()[
            "data"
        ]
        == []
    )
    assert (
        client.get(
            "/api/v1/events", params={"from": "2026-01-01T00:00:00.100Z"}
        ).json()["meta"]["total"]
        == 3
    )


def test_half_open_run_windows_timezone_and_single_bounds(client, known_data):
    params = {
        "start_time": "2026-01-01T08:00:00+08:00",
        "end_time": "2026-01-03T08:00:00+08:00",
    }
    runs = client.get("/api/v1/runs", params=params).json()
    assert [row["run_id"] for row in runs["data"]] == known_data["run_ids"][:1]
    assert (
        client.get("/api/v1/runs", params={"end_time": params["end_time"]}).json()[
            "meta"
        ]["total"]
        == 1
    )
    assert (
        client.get(
            "/api/v1/analytics/overview", params={"to": params["end_time"]}
        ).json()["data"]["total_runs"]
        == 1
    )


@pytest.mark.parametrize("path", ["overview", "agents", "tools", "errors", "trend"])
@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-01-01"},
        {"to": "invalid"},
        {"from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
        {"start_time": "2026-01-01T00:00:00Z"},
    ],
)
def test_analytics_time_validation(client, path, params):
    assert client.get(f"/api/v1/analytics/{path}", params=params).status_code == 422
