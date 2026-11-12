"""Protocol tests use a local HTTP fake, separately from real PostgreSQL acceptance."""

import importlib.util
import json
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest

spec = importlib.util.spec_from_file_location(
    "generate_data", Path(__file__).resolve().parents[3] / "scripts/generate_data.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


@pytest.fixture
def http_api(monkeypatch):
    task_id = str(uuid4())
    state = {
        "calls": Counter(),
        "configs": [],
        "runs": [],
        "span_count": 5,
        "statuses": ["RUNNING", "SUCCESS"],
        "faults": {},
        "task_id": task_id,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.respond("POST")

        def do_GET(self):
            self.respond("GET")

        def respond(self, method):
            path = self.path.removeprefix("/api/v1")
            body = None
            if method == "POST":
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            key = (method, path)
            state["calls"][key] += 1
            faults = state["faults"].get(key, [])
            if faults:
                fault = faults.pop(0)
                if fault == "disconnect":
                    self.close_connection = True
                    return
                if fault == "truncated":
                    self.send_response(200 if method == "GET" else 201)
                    self.send_header("Content-Length", "999")
                    self.end_headers()
                    self.wfile.write(b'{"data":')
                    self.close_connection = True
                    return
                self.send_response(fault)
                self.end_headers()
                self.wfile.write(b"invalid JSON")
                return
            if path == "/tasks":
                data = {"task_id": task_id}
                status = 201 if method == "POST" else 200
            elif method == "POST":
                assert path == f"/tasks/{task_id}/runs"
                state["configs"].append(body["simulation_config"])
                data = {
                    "run_id": str(uuid4()),
                    "trace_id": uuid4().hex,
                    "status": "RUNNING",
                }
                state["runs"].append(data)
                status = 202
            elif path.startswith("/runs/"):
                statuses = state["statuses"]
                current = statuses.pop(0) if len(statuses) > 1 else statuses[0]
                data = state["runs"][-1] | {"status": current}
                status = 200
            else:
                assert path == f"/traces/{state['runs'][-1]['trace_id']}"
                data = state["runs"][-1] | {
                    "span_count": state["span_count"],
                    "status": state["statuses"][-1],
                }
                status = 200
            payload = json.dumps({"data": data}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    thread.start()
    monkeypatch.setattr(generator, "POLL_INTERVAL", 0)
    yield f"http://127.0.0.1:{server.server_port}/api/v1", state
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def run_cli(base_url, *extra):
    return generator.main(
        [
            "--base-url",
            base_url,
            "--runs",
            "2",
            "--spans-per-run",
            "5",
            *extra,
        ]
    )


def test_defaults_and_argument_validation():
    args = generator.parse_args([])
    assert (
        args.base_url,
        args.runs,
        args.spans_per_run,
        args.seed,
        args.agent_ids,
    ) == (
        "http://127.0.0.1:8000/api/v1",
        200,
        500,
        42,
        None,
    )
    for flags in (
        ["--runs", "0"],
        ["--runs", "bad"],
        ["--spans-per-run", "501"],
        ["--spans-per-run", "-1"],
        ["--agent-ids", ""],
        ["--agent-ids", "bad"],
        ["--agent-ids", ",".join([str(uuid4())] * 2)],
        ["--agent-ids", ",".join(str(uuid4()) for _ in range(4))],
        ["--base-url", "file:///tmp"],
        ["--base-url", "http://localhost/?q=x"],
    ):
        with pytest.raises(SystemExit) as exc:
            generator.parse_args(flags)
        assert exc.value.code == 2


def test_success_unbound_and_seeds(http_api, capsys):
    base_url, state = http_api
    assert run_cli(base_url) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["complete"] is True
    assert summary["actual_spans"] == 10
    assert (
        summary["accepted_runs"]
        == summary["completed_runs"]
        == summary["success_runs"]
        == 2
    )
    assert summary["task_id"] == state["task_id"]
    assert [cfg["seed"] for cfg in state["configs"]] == [42, 43]
    assert all("agent_ids" not in cfg for cfg in state["configs"])
    assert state["calls"][("POST", "/tasks")] == 1


def test_bound_serialization_failed_run_with_full_trace(http_api, capsys):
    base_url, state = http_api
    state["statuses"] = ["FAILED"]
    ids = [str(uuid4()) for _ in range(2)]
    assert run_cli(base_url, "--agent-ids", ",".join(ids)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["failed_runs"] == 2
    assert summary["actual_spans"] == 10
    for cfg in state["configs"]:
        assert cfg["agent_ids"] == ids
        assert cfg["agent_count"] == 2
        assert cfg["min_spans"] == cfg["max_spans"] == 5


@pytest.mark.parametrize("fault", [500, 409, 422, "disconnect", "truncated"])
@pytest.mark.parametrize("resource", ["task", "run"])
def test_post_never_retried(http_api, capsys, fault, resource):
    base_url, state = http_api
    path = "/tasks" if resource == "task" else f"/tasks/{state['task_id']}/runs"
    state["faults"][("POST", path)] = [fault]
    assert run_cli(base_url) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["complete"] is False
    assert state["calls"][("POST", path)] == 1
    assert summary["actual_spans"] == 0


def test_get_retry_and_retry_exhaustion(http_api, capsys):
    base_url, state = http_api
    client = generator.ApiClient(base_url)
    # The fake accepts the task route for GET to exercise transport behavior alone.
    key = ("GET", "/tasks")
    state["faults"][key] = [503, 429]
    assert client.request("GET", "/tasks")["task_id"] == state["task_id"]
    assert state["calls"][key] == 3
    state["faults"][key] = [500, 500, 500]
    with pytest.raises(generator.GenerationError, match="3 attempt"):
        client.request("GET", "/tasks")
    assert state["calls"][key] == 6
    state["faults"][key] = [404]
    with pytest.raises(generator.GenerationError, match="404"):
        client.request("GET", "/tasks")
    assert state["calls"][key] == 7
    state["faults"][key] = ["truncated", "disconnect"]
    assert client.request("GET", "/tasks")["task_id"] == state["task_id"]
    assert state["calls"][key] == 10


@pytest.mark.parametrize("count", [0, 4, True, "5", 501])
def test_invalid_or_insufficient_counts_fail(http_api, capsys, count):
    base_url, state = http_api
    state["span_count"] = count
    assert run_cli(base_url) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["complete"] is False
    assert summary["accepted_runs"] == 1, summary
    assert summary["actual_spans"] == (
        count if type(count) is int and count <= 500 else 0
    )


def test_poll_timeout_and_unknown_status(http_api, monkeypatch, capsys):
    base_url, state = http_api
    state["statuses"] = ["RUNNING"]
    ticks = count()
    monkeypatch.setattr(
        generator,
        "time",
        SimpleNamespace(
            monotonic=lambda: next(ticks),
            sleep=lambda _: None,
        ),
    )
    monkeypatch.setattr(generator, "RUN_TIMEOUT", 5)
    assert run_cli(base_url) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["accepted_runs"] == 1, summary
    assert summary["completed_runs"] == 0
    assert summary["last_run_id"]
    state["statuses"] = ["CANCELLED"]
    monkeypatch.setattr(generator, "RUN_TIMEOUT", 120)
    assert run_cli(base_url) == 1
    assert "unexpected status" in capsys.readouterr().err


def test_malformed_json_and_redirect_not_retried(http_api):
    base_url, state = http_api
    client = generator.ApiClient(base_url)
    state["faults"][("GET", "/tasks")] = [200]
    with pytest.raises(generator.GenerationError, match="JSON"):
        client.request("GET", "/tasks")
    state["faults"][("POST", "/tasks")] = [302]
    with pytest.raises(generator.GenerationError, match="302"):
        client.request("POST", "/tasks", {})
    assert state["calls"][("POST", "/tasks")] == 1
