"""Opt-in, isolated PostgreSQL experiments with real plans and durable history."""

import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.core.config import ROOT, database_url
from app.core.errors import AppError
from app.schemas.v1 import BenchmarkResult

RESULTS_PATH = ROOT / "backend/var/benchmarks.json"
MAX_SECONDS = 120
_run_lock = threading.Lock()
_history_lock = threading.Lock()
_results = TypeAdapter(list[BenchmarkResult])


def _read_history():
    try:
        with _history_lock:
            content = RESULTS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except UnicodeError as exc:
        raise AppError(500, "INTERNAL_ERROR", "Benchmark history is invalid") from exc
    try:
        rows = _results.validate_json(content)
        if len({r.result_id for r in rows}) != len(rows):
            raise ValueError("Duplicate result IDs")
        return [r.model_dump(mode="json") for r in rows]
    except (ValueError, ValidationError) as exc:
        raise AppError(500, "INTERNAL_ERROR", "Benchmark history is invalid") from exc


def history(query):
    rows = _read_history()
    rows.sort(key=lambda row: row["result_id"])
    rows.sort(key=lambda row: datetime.fromisoformat(row["created_at"]), reverse=True)
    start = (query.page - 1) * query.page_size
    return {
        "data": rows[start : start + query.page_size],
        "meta": {"page": query.page, "page_size": query.page_size, "total": len(rows)},
    }


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AppError(504, "BENCHMARK_TIMEOUT", "Benchmark exceeded its time limit")
    return remaining


def _execute(conn, deadline, sql, parameters=None):
    milliseconds = max(1, math.ceil(_remaining(deadline) * 1000))
    conn.execute(
        text("SELECT set_config('statement_timeout', :timeout, true)"),
        {"timeout": str(milliseconds)},
    )
    result = conn.execute(text(sql), parameters or {})
    _remaining(deadline)
    return result


def _measure(conn, deadline, sql, parameters):
    plans = []
    for _ in range(3):
        plan = _execute(
            conn, deadline, "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, parameters
        ).scalar_one()[0]
        plans.append(plan)
    return sorted(plans, key=lambda plan: plan["Execution Time"])[1]


def _experiment(request, deadline):
    # A separate physical connection owns all temporary tables and is closed even
    # after cancellation. No experiment DDL ever targets public tables/indexes.
    engine = create_engine(
        database_url(),
        poolclass=NullPool,
        connect_args={
            "connect_timeout": min(5, max(1, math.ceil(_remaining(deadline)))),
            "options": "-c timezone=UTC",
        },
    )
    try:
        with engine.connect() as conn:
            driver = conn.connection.driver_connection
            timer = threading.Timer(_remaining(deadline), driver.cancel)
            timer.daemon = True
            timer.start()
            try:
                with conn.begin():
                    _execute(
                        conn,
                        deadline,
                        """
                        CREATE TEMP TABLE benchmark_spans
                        (LIKE public.spans INCLUDING DEFAULTS INCLUDING CONSTRAINTS
                         INCLUDING IDENTITY) ON COMMIT DROP
                    """,
                    )
                    _execute(
                        conn,
                        deadline,
                        """
                        INSERT INTO pg_temp.benchmark_spans
                        (run_id, span_id, parent_span_id, operation_type, span_name,
                         status, start_time, end_time, tool_name, error_type, attributes)
                        SELECT md5((((i-1)/500)+1)::text)::uuid,
                               lpad(to_hex(i),16,'0'),
                               CASE WHEN (i-1) % 500 = 0 THEN NULL
                                    ELSE lpad(to_hex(((i-1)/500)*500+1),16,'0') END,
                               CASE WHEN (i-1) % 500 = 0 THEN 'WORKFLOW' ELSE 'TOOL' END,
                               'benchmark ' || i,
                               CASE WHEN i % 100 = 0 THEN 'ERROR' ELSE 'SUCCESS' END,
                               timestamptz '2026-01-01 00:00:00+00' + i * interval '1 ms',
                               timestamptz '2026-01-01 00:00:00+00' + (i+1) * interval '1 ms',
                               'benchmark_tool',
                               CASE WHEN i % 100 = 0 THEN 'BenchmarkError' ELSE NULL END,
                               '{}'::jsonb
                        FROM generate_series(1, :size) AS g(i)
                    """,
                        {"size": request.dataset_size},
                    )
                    _execute(conn, deadline, "ANALYZE pg_temp.benchmark_spans")
                    size = _execute(
                        conn, deadline, "SELECT count(*) FROM pg_temp.benchmark_spans"
                    ).scalar_one()
                    if request.case_code == "TRACE_QUERY_INDEX":
                        sql = """SELECT * FROM pg_temp.benchmark_spans
                                 WHERE run_id = md5('1')::uuid
                                 AND start_time >= timestamptz '2026-01-01 00:00:00+00'
                                 ORDER BY start_time"""
                        index = "CREATE INDEX ON pg_temp.benchmark_spans(run_id, start_time)"
                        strategy = "no_index_vs_run_start"
                        parameters = {}
                    else:
                        sql = """SELECT * FROM pg_temp.benchmark_spans
                                 WHERE status = 'ERROR'
                                 AND start_time >= timestamptz '2026-01-01 00:00:00+00'
                                     + :threshold * interval '1 ms'
                                 ORDER BY start_time DESC"""
                        index = """CREATE INDEX ON pg_temp.benchmark_spans(start_time DESC)
                                   WHERE status = 'ERROR'"""
                        strategy = "no_index_vs_error_partial"
                        parameters = {"threshold": request.dataset_size // 2}
                    before = _measure(conn, deadline, sql, parameters)
                    _execute(conn, deadline, index)
                    _execute(conn, deadline, "ANALYZE pg_temp.benchmark_spans")
                    after = _measure(conn, deadline, sql, parameters)
                    return {
                        "result_id": str(uuid4()),
                        "case_code": request.case_code,
                        "dataset_size": size,
                        "index_strategy": strategy,
                        "duration_ms": after["Execution Time"],
                        "plan": {
                            "before": before,
                            "after": after,
                            "duration_before_ms": before["Execution Time"],
                            "duration_after_ms": after["Execution Time"],
                            "repeats": 3,
                        },
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
            finally:
                timer.cancel()
                timer.join()
    except DBAPIError as exc:
        if (
            getattr(exc.orig, "sqlstate", None) == "57014"
            or time.monotonic() >= deadline
        ):
            raise AppError(
                504, "BENCHMARK_TIMEOUT", "Benchmark exceeded its time limit"
            ) from exc
        raise
    finally:
        engine.dispose()


def _save(rows, deadline):
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(str(RESULTS_PATH) + f".{uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as file:
            json.dump(rows, file, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        _remaining(deadline)
        # Windows readers may temporarily prevent replacement of an open file.
        # Serialize only file access; GET remains available during SQL execution.
        with _history_lock:
            _remaining(deadline)
            os.replace(temp, RESULTS_PATH)
    finally:
        temp.unlink(missing_ok=True)


def run(request):
    if os.getenv("BENCHMARK_ENABLED", "false").lower() not in {"true", "1", "yes"}:
        raise AppError(409, "FEATURE_NOT_AVAILABLE", "Benchmarks are disabled")
    if not _run_lock.acquire(blocking=False):
        raise AppError(409, "CONFLICT", "A benchmark is already running")
    try:
        deadline = time.monotonic() + MAX_SECONDS
        previous = _read_history()  # Never overwrite corrupt existing history.
        result = BenchmarkResult.model_validate(
            _experiment(request, deadline)
        ).model_dump(mode="json")
        _save([*previous, result], deadline)
        return result
    finally:
        _run_lock.release()
