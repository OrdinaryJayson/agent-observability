"""Explicit HTTP endurance check; not discovered by the default test suite.

Set B_ENDURANCE_SECONDS (default 30) and optionally B_ENDURANCE_REPORT.
The standard test entry point selects and clears a dedicated *_test database.
"""

import json
import os
from pathlib import Path
import site
import socket
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]


def serve(config_path):
    import uvicorn

    from app.services import benchmarks

    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    benchmarks.RESULTS_PATH = Path(config["history"])
    server = uvicorn.Server(
        uvicorn.Config("app.main:app", host="127.0.0.1", port=config["port"])
    )

    def watch_stop():
        while not Path(config["stop"]).exists():
            time.sleep(0.1)
        server.should_exit = True

    threading.Thread(target=watch_stop, daemon=True).start()
    server.run()


def test_http_endurance_with_process_restarts(db, tmp_path):
    seconds = float(os.getenv("B_ENDURANCE_SECONDS", "30"))
    assert 0 < seconds <= 14400
    report_path = Path(os.getenv("B_ENDURANCE_REPORT", str(tmp_path / "report.json")))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    stop_path = tmp_path / "stop"
    config_path = tmp_path / "server.json"
    config_path.write_text(
        json.dumps(
            {
                "port": port,
                "stop": str(stop_path),
                "history": str(tmp_path / "benchmarks.json"),
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["BENCHMARK_ENABLED"] = "true"
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), *site.getsitepackages()])
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "cycles": 0,
        "spans": 0,
        "success_runs": 0,
        "failed_runs": 0,
        "benchmarks": 0,
        "restarts": 0,
        "sampled_max_connections": 0,
        "errors": [],
    }
    latencies = []
    process = None
    client = None
    server_log = (tmp_path / "server.log").open("w", encoding="utf-8")

    def save():
        report["updated_at"] = datetime.now(timezone.utc).isoformat()
        report["query_p50_ms"] = statistics.median(latencies) if latencies else None
        report["query_max_ms"] = max(latencies) if latencies else None
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    def start():
        nonlocal process, client
        stop_path.unlink(missing_ok=True)
        # The base interpreter avoids Windows' venv launcher child process;
        # PYTHONPATH supplies the same locked virtual-environment packages.
        process = subprocess.Popen(
            [
                sys._base_executable,
                str(Path(__file__).resolve()),
                "--serve",
                str(config_path),
            ],
            cwd=ROOT,
            env=env,
            stdout=server_log,
            stderr=server_log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=150
        )
        ready = time.monotonic() + 15
        while time.monotonic() < ready:
            assert process.poll() is None, (tmp_path / "server.log").read_text()
            try:
                if client.get("/health").status_code == 200:
                    return
            except httpx.ConnectError:
                pass
            time.sleep(0.1)
        raise AssertionError("HTTP server did not become ready")

    def stop():
        if client is not None:
            client.close()
        stop_path.touch()
        if process is not None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise AssertionError("HTTP server failed to stop gracefully")
            assert process.returncode == 0

    def request(method, path, expected=200, **kwargs):
        begin = time.monotonic()
        response = client.request(method, "/api/v1" + path, **kwargs)
        assert response.status_code == expected, response.text
        return response.json(), (time.monotonic() - begin) * 1000

    def check_totals():
        data = request("GET", "/analytics/overview")[0]["data"]
        for key, expected in {
            "total_runs": report["cycles"],
            "total_spans": report["spans"],
            "success_runs": report["success_runs"],
            "failed_runs": report["failed_runs"],
        }.items():
            assert data[key] == expected, (key, data[key], expected)
        history = request("GET", "/benchmarks/results")[0]
        assert history["meta"]["total"] == report["benchmarks"]

    try:
        start()
        task_id = request("POST", "/tasks", 201, json={"title": "HTTP endurance"})[0][
            "data"
        ]["task_id"]
        deadline = time.monotonic() + seconds
        paths = [
            "/analytics/" + key
            for key in ("overview", "agents", "tools", "errors", "trend")
        ]
        paths += ["/runs", "/events", "/tasks"]
        with ThreadPoolExecutor(max_workers=6) as readers:
            while time.monotonic() < deadline:
                begin = time.monotonic()
                index = report["cycles"]
                fail = index % 5 == 0
                run = request(
                    "POST",
                    f"/tasks/{task_id}/runs",
                    202,
                    json={
                        "simulation_config": {
                            "min_spans": 500,
                            "max_spans": 500,
                            "failure_rate": int(fail),
                            "seed": index + 73,
                        }
                    },
                )[0]["data"]
                for body, elapsed in readers.map(
                    lambda path: request("GET", path), paths
                ):
                    latencies.append(elapsed)
                    if "meta" in body:
                        assert len(body["data"]) <= body["meta"]["total"]
                terminal = time.monotonic() + 15
                while time.monotonic() < terminal:
                    state = request("GET", "/runs/" + run["run_id"])[0]["data"]
                    if state["status"] != "RUNNING":
                        break
                    time.sleep(0.05)
                assert state["status"] == ("FAILED" if fail else "SUCCESS")
                trace = request("GET", "/traces/" + run["trace_id"])[0]["data"]
                assert trace["span_count"] == 500
                report["cycles"] += 1
                report["spans"] += 500
                report["failed_runs" if fail else "success_runs"] += 1
                if index % 10 == 0:
                    for case in ("TRACE_QUERY_INDEX", "ERROR_PARTIAL_INDEX"):
                        result = request(
                            "POST",
                            "/benchmarks/run",
                            201,
                            json={"case_code": case, "dataset_size": 100000},
                        )[0]["data"]
                        assert result["dataset_size"] == 100000
                        report["benchmarks"] += 1
                check_totals()
                with db.connect() as conn:
                    assert (
                        conn.scalar(text("SELECT count(*) FROM spans"))
                        == report["spans"]
                    )
                    assert (
                        conn.scalar(
                            text(
                                "SELECT count(*) FROM pg_class WHERE relname='benchmark_spans'"
                            )
                        )
                        == 0
                    )
                    connections = conn.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()"
                        )
                    )
                    assert connections <= 20
                    report["sampled_max_connections"] = max(
                        report["sampled_max_connections"], connections
                    )
                if index % 10 == 0:
                    stop()
                    start()
                    report["restarts"] += 1
                    check_totals()
                    assert (
                        request("GET", "/traces/" + run["trace_id"])[0]["data"] == trace
                    )
                save()
                print(json.dumps(report), flush=True)
                delay = min(
                    deadline - time.monotonic(), max(0, 30 - (time.monotonic() - begin))
                )
                if delay > 0:
                    time.sleep(delay)
        report["status"] = "passed"
    except BaseException as exc:
        report["status"] = "failed"
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            stop()
        except BaseException as exc:
            report["status"] = "failed"
            report["errors"].append(f"Shutdown: {type(exc).__name__}: {exc}")
            raise
        finally:
            server_log.close()
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            save()


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--serve":
    serve(sys.argv[2])
