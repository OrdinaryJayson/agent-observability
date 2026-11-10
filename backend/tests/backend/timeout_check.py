"""Explicit 120-second acceptance; excluded from default test discovery."""

import time

from sqlalchemy import text

from app.services import benchmarks


def test_actual_120_second_deadline_and_recovery(client, db, monkeypatch, tmp_path):
    path = tmp_path / "deadline-history.json"
    monkeypatch.setattr(benchmarks, "RESULTS_PATH", path)
    monkeypatch.setenv("BENCHMARK_ENABLED", "true")
    assert benchmarks.MAX_SECONDS == 120

    def slow_measure(conn, deadline, sql, parameters):
        benchmarks._execute(conn, deadline, "SELECT pg_sleep(130)")
        raise AssertionError("The SQL timeout did not cancel the operation")

    with monkeypatch.context() as patch:
        patch.setattr(benchmarks, "_measure", slow_measure)
        started = time.monotonic()
        response = client.post(
            "/api/v1/benchmarks/run",
            json={
                "case_code": "TRACE_QUERY_INDEX",
                "dataset_size": 1000,
            },
        )
        elapsed = time.monotonic() - started
    assert response.status_code == 504, response.text
    assert response.json()["error"]["code"] == "BENCHMARK_TIMEOUT"
    assert 119 <= elapsed < 125
    assert not path.exists()
    with db.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM pg_class WHERE relname='benchmark_spans'")
            )
            == 0
        )
    recovery = client.post(
        "/api/v1/benchmarks/run",
        json={
            "case_code": "ERROR_PARTIAL_INDEX",
            "dataset_size": 1000,
        },
    )
    assert recovery.status_code == 201, recovery.text
    assert client.get("/api/v1/benchmarks/results").json()["meta"]["total"] == 1
    print(
        f"Actual deadline elapsed: {elapsed:.3f} seconds; cleanup and next experiment verified"
    )
