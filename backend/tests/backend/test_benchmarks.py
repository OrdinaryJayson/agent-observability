import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import text

from app.core.errors import AppError
from app.schemas.v1 import BenchmarkRequest, Pagination
from app.services import benchmarks


@pytest.fixture
def isolated_history(monkeypatch, tmp_path):
    path = tmp_path / "benchmarks.json"
    monkeypatch.setattr(benchmarks, "RESULTS_PATH", path)
    monkeypatch.setenv("BENCHMARK_ENABLED", "true")
    return path


@pytest.mark.parametrize("case", ["TRACE_QUERY_INDEX", "ERROR_PARTIAL_INDEX"])
@pytest.mark.parametrize("size", [1000, 10000, 100000])
def test_real_plans_all_cases_and_scales(client, db, isolated_history, case, size):
    with db.connect() as conn:
        indexes_before = conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY indexname"
            )
        ).all()
    response = client.post(
        "/api/v1/benchmarks/run", json={"case_code": case, "dataset_size": size}
    )
    assert response.status_code == 201, response.text
    result = response.json()["data"]
    assert result["dataset_size"] == size
    assert result["case_code"] == case
    plan = result["plan"]
    assert plan["repeats"] == 3
    assert plan["before"]["Execution Time"] == plan["duration_before_ms"]
    assert (
        plan["after"]["Execution Time"]
        == plan["duration_after_ms"]
        == result["duration_ms"]
    )
    assert plan["before"]["Plan"]["Actual Rows"] == plan["after"]["Plan"]["Actual Rows"]
    # Never assert a fabricated speedup: PostgreSQL chooses the actual plan.
    assert plan["duration_before_ms"] >= 0 and plan["duration_after_ms"] >= 0
    assert json.loads(isolated_history.read_text())[0] == result
    assert client.get("/api/v1/benchmarks/results").json()["data"] == [result]
    with db.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY indexname"
                )
            ).all()
            == indexes_before
        )
        assert conn.scalar(text("SELECT count(*) FROM spans")) == 0
        assert (
            conn.scalar(
                text("SELECT count(*) FROM pg_class WHERE relname='benchmark_spans'")
            )
            == 0
        )


def test_disabled_and_history_pagination(client, isolated_history, monkeypatch):
    monkeypatch.setenv("BENCHMARK_ENABLED", "false")
    response = client.post(
        "/api/v1/benchmarks/run",
        json={"case_code": "TRACE_QUERY_INDEX", "dataset_size": 1000},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FEATURE_NOT_AVAILABLE"
    assert client.get("/api/v1/benchmarks/results").json()["meta"]["total"] == 0
    assert not isolated_history.exists()


@pytest.mark.parametrize(
    "body",
    [
        {"case_code": "arbitrary SQL", "dataset_size": 1000},
        {"case_code": "TRACE_QUERY_INDEX", "dataset_size": 1001},
        {"case_code": "TRACE_QUERY_INDEX", "dataset_size": 1000, "sql": "SELECT 1"},
    ],
)
def test_invalid_experiment(client, body):
    assert client.post("/api/v1/benchmarks/run", json=body).status_code == 422


def test_corrupt_history_is_not_silently_overwritten(client, isolated_history):
    isolated_history.write_text('{"broken": true}')
    # Use public error handling without having TestClient re-raise generic errors.
    assert client.get("/api/v1/benchmarks/results").status_code == 500
    response = client.post(
        "/api/v1/benchmarks/run",
        json={"case_code": "TRACE_QUERY_INDEX", "dataset_size": 1000},
    )
    assert response.status_code == 500
    assert isolated_history.read_text() == '{"broken": true}'


def test_concurrent_request_conflicts_and_lock_recovers(
    db, isolated_history, monkeypatch
):
    entered, release = Event(), Event()

    def blocked(request, deadline):
        entered.set()
        assert release.wait(10)
        raise AppError(504, "BENCHMARK_TIMEOUT", "test timeout")

    monkeypatch.setattr(benchmarks, "_experiment", blocked)
    request = BenchmarkRequest(case_code="TRACE_QUERY_INDEX", dataset_size=1000)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(benchmarks.run, request)
        assert entered.wait(10)
        try:
            with pytest.raises(AppError) as conflict:
                benchmarks.run(request)
            assert conflict.value.status == 409
        finally:
            release.set()
        with pytest.raises(AppError):
            future.result(timeout=10)
    assert not isolated_history.exists()
    assert benchmarks._run_lock.acquire(blocking=False)
    benchmarks._run_lock.release()


def test_real_sql_timeout_cleans_up_and_does_not_append(
    client, db, isolated_history, monkeypatch
):
    original = benchmarks._measure

    def slow(conn, deadline, sql, parameters):
        benchmarks._execute(conn, deadline, "SELECT pg_sleep(2)")
        return original(conn, deadline, sql, parameters)

    monkeypatch.setattr(benchmarks, "MAX_SECONDS", 0.3)
    monkeypatch.setattr(benchmarks, "_measure", slow)
    start = time.monotonic()
    response = client.post(
        "/api/v1/benchmarks/run",
        json={"case_code": "TRACE_QUERY_INDEX", "dataset_size": 1000},
    )
    assert response.status_code == 504, response.text
    assert response.json()["error"]["code"] == "BENCHMARK_TIMEOUT"
    assert time.monotonic() - start < 5
    assert not isolated_history.exists()
    with db.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM pg_class WHERE relname='benchmark_spans'")
            )
            == 0
        )


def test_failed_save_preserves_existing_history(db, isolated_history, monkeypatch):
    request = BenchmarkRequest(case_code="TRACE_QUERY_INDEX", dataset_size=1000)
    first = benchmarks.run(request)
    original = isolated_history.read_bytes()

    def fail_replace(*args):
        raise OSError("simulated disk error")

    monkeypatch.setattr(benchmarks.os, "replace", fail_replace)
    with pytest.raises(OSError):
        benchmarks.run(request)
    assert isolated_history.read_bytes() == original
    assert not list(isolated_history.parent.glob("*.tmp"))
    assert benchmarks.history(Pagination())["data"] == [first]
    assert benchmarks.history(Pagination(page=2))["data"] == []


def test_invalid_utf8_history_reports_internal_error(client, isolated_history):
    isolated_history.write_bytes(b"\xff\xfe")
    response = client.get("/api/v1/benchmarks/results")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"


def test_readers_observe_only_complete_history_during_atomic_replace(
    db, isolated_history
):
    request = BenchmarkRequest(case_code="ERROR_PARTIAL_INDEX", dataset_size=1000)
    first = benchmarks.run(request)
    done = Event()
    totals = []

    def read():
        while not done.is_set():
            rows = benchmarks.history(Pagination())["data"]
            assert first in rows
            assert len({row["result_id"] for row in rows}) == len(rows)
            totals.append(len(rows))

    with ThreadPoolExecutor(1) as pool:
        reader = pool.submit(read)
        try:
            second = benchmarks.run(request)
        finally:
            done.set()
        reader.result(timeout=5)
    assert totals and set(totals) <= {1, 2}
    assert benchmarks.history(Pagination())["data"] == [second, first]


def test_history_sorts_instants_with_fractional_seconds_and_timezone_offsets(
    client, db, isolated_history
):
    template = benchmarks.run(
        BenchmarkRequest(case_code="TRACE_QUERY_INDEX", dataset_size=1000)
    )
    entries = [
        {
            **template,
            "result_id": f"00000000-0000-0000-0000-{number:012d}",
            "created_at": created_at,
        }
        for number, created_at in (
            (1, "2026-01-01T00:00:00Z"),
            (3, "2026-01-01T00:00:00.100000Z"),
            (2, "2026-01-01T08:00:00.100000+08:00"),
        )
    ]
    isolated_history.write_text(json.dumps(entries), encoding="utf-8")
    first = client.get("/api/v1/benchmarks/results?page_size=2").json()
    second = client.get("/api/v1/benchmarks/results?page_size=2&page=2").json()
    assert first["meta"] == {"page": 1, "page_size": 2, "total": 3}
    assert [row["result_id"] for row in first["data"] + second["data"]] == [
        entries[index]["result_id"] for index in (2, 1, 0)
    ]
