import os
import queue
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import text

from app.repositories import execution


def test_live_sse_pool_budget_and_api_startup_recovery(prepared, db):
    accepted = prepared["start"]("live-http-run-0001")["data"]
    with db.begin() as conn:
        legacy = execution.create_run(conn, prepared["task"]["task_id"])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env={**os.environ, "PGAPPNAME": "B-v2-api-probe"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    base = f"http://127.0.0.1:{port}"
    run_path = "/api/v2/runs/" + accepted["run_id"]
    ready = queue.Queue()

    def subscribe():
        with httpx.Client(base_url=base, trust_env=False, timeout=10) as subscriber:
            with subscriber.stream("GET", run_path + "/stream?after_seq=1") as response:
                assert response.status_code == 200
                ready.put(True)
                return [
                    int(line[4:])
                    for line in response.iter_lines()
                    if line.startswith("id: ")
                ]

    try:
        with httpx.Client(base_url=base, trust_env=False, timeout=3) as client:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if process.poll() is not None:
                    raise AssertionError("Owned API process exited before health check")
                time.sleep(0.05)
            else:
                raise AssertionError("API startup exceeded ten seconds")
            assert client.get(run_path).json()["data"]["execution_state"] == "QUEUED"
            with db.connect() as conn:
                assert execution.get_run(conn, legacy["run_id"])["status"] == "FAILED"
            snapshot = client.get(run_path + "/snapshot").json()["data"]
            assert snapshot["seq"] == 1 and not snapshot["projection_complete"]
            cors = client.options(
                run_path + "/cancel",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Idempotency-Key,If-Match,Last-Event-ID",
                },
            )
            assert cors.status_code == 200
            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = [pool.submit(subscribe) for _ in range(10)]
                try:
                    for _ in range(10):
                        ready.get(timeout=10)
                    with db.connect() as conn:
                        assert (
                            conn.scalar(
                                text(
                                    "SELECT count(*) FROM pg_stat_activity WHERE application_name='B-v2-api-probe'"
                                )
                            )
                            <= 4
                        )
                        assert (
                            conn.scalar(
                                text(
                                    "SELECT count(*) FROM pg_stat_activity WHERE application_name='B-v2-api-probe' AND state='idle in transaction'"
                                )
                            )
                            == 0
                        )
                finally:
                    response = client.post(run_path + "/cancel", json={})
                    assert response.status_code == 200
                assert all(future.result(timeout=10) == [2, 3] for future in futures)
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
