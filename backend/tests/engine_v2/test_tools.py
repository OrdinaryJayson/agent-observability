from collections import Counter
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest

from _common import HttpClient, StateFile, ToolError
from _datasets import DatasetChecker, iter_dataset
from _stream import consume_stream
from report_experiments import paired_bootstrap, quantile, summarize
import fault_suite
import generate_dataset
import load_test
import report_experiments
import seed_demo
import check_run


@pytest.fixture
def http_service():
    state = {
        "calls": Counter(),
        "keys": {},
        "faults": {},
        "runs": {},
        "datasets": {},
        "seq": 2,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.respond("POST")

        def do_GET(self):
            self.respond("GET")

        def respond(self, method):
            path = self.path
            body = (
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if method == "POST"
                else None
            )
            state["calls"][(method, path)] += 1
            faults = state["faults"].get((method, path), [])
            if faults:
                code = faults.pop(0)
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b"failure")
                return
            if "/stream?" in path:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"event: stream.end\ndata: {}\n\n")
                return
            if path.endswith("/agents"):
                data = {"agent_id": str(uuid4()), **body}
            elif path.endswith("/tasks"):
                data = {"task_id": str(uuid4()), **body}
            elif path.endswith("/workflows"):
                data = {"workflow_id": str(uuid4()), "revision": 1, **body}
            elif path.endswith("/validate"):
                data = {"valid": True, "errors": []}
            elif path.endswith("/versions"):
                assert self.headers["If-Match"] == '"1"'
                data = {"version_id": str(uuid4())}
            elif path.endswith("/datasets"):
                data = {"dataset_id": str(uuid4()), "state": "BUILDING", **body}
                state["datasets"][data["dataset_id"]] = data
            elif path.endswith("/finalize"):
                data = {"state": "READY", **body}
            elif method == "POST" and path.endswith("/runs"):
                key = self.headers["Idempotency-Key"]
                data = state["keys"].get(key)
                if data is None:
                    data = {
                        "run_id": str(uuid4()),
                        "trace_id": uuid4().hex,
                        "status": "RUNNING",
                    }
                    state["keys"][key] = data
                    state["runs"][data["run_id"]] = data | {
                        "status": "SUCCESS",
                        "span_count": 0,
                        "queue_duration_ms": 0,
                        "execution_duration_ms": 0,
                    }
            elif path.endswith("/cancel"):
                run_id = path.split("/")[-2]
                state["runs"][run_id]["status"] = "CANCELLED"
                data = {"accepted": True}
            elif path.endswith("/snapshot"):
                data = {
                    "seq": state["seq"],
                    "projection_complete": True,
                    "nodes": [],
                    "spans": [],
                    "run": state["runs"][path.split("/")[-2]],
                }
            elif "/runs/" in path:
                data = state["runs"][path.split("/")[-1]]
            else:
                data = {"value": "ok"}
            payload = json.dumps({"data": data}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/api/v2", state
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.mark.parametrize("payload_bytes", [128, 1024, 4096])
@pytest.mark.parametrize("distribution", ["uniform", "hotspot"])
def test_dataset_shape_digest_and_distributions(payload_bytes, distribution):
    options = dict(
        profile="BENCH_100K", distribution=distribution, payload_bytes=payload_bytes
    )
    bundle = next(iter_dataset(**options))
    first = DatasetChecker()
    first.consume(bundle)
    assert first.summary()["actual_counts"]["spans"] == 500
    assert first.summary()["actual_counts"]["agents"] == 100
    second = DatasetChecker()
    duplicate = deepcopy(bundle)
    duplicate["spans"][0]["start_time"] = "2025-01-01T00:00:00Z"
    second.consume(duplicate)
    assert first.summary()["content_hash"] == second.summary()["content_hash"]
    duplicate["spans"][0]["parent_span_id"] = "f" * 16
    with pytest.raises(ToolError):
        DatasetChecker().consume(duplicate)


def test_type7_and_paired_bootstrap_with_known_answers():
    assert quantile(list(range(1, 16)), 0.95) == pytest.approx(14.3)
    difference, interval = paired_bootstrap(
        {index: index for index in range(15)}, {index: index - 2 for index in range(15)}
    )
    assert difference == -2
    assert interval == [-2, -2]
    assert paired_bootstrap({}, {}) == (None, None)
    samples = [
        {
            "repetition": index,
            "is_warmup": index < 3,
            "metrics": {"execution_ms": index},
            "correctness": {"passed": True},
        }
        for index in range(18)
    ]
    result, _ = summarize(samples)
    assert result["n"] == 15 and result["median_ms"] == 10
    samples[5]["metrics"]["execution_ms"] = None
    result, _ = summarize(samples)
    assert result["failed_samples"] == 1 and result["n"] == 14


def test_http_idempotency_and_unknown_non_idempotent_post(http_service, tmp_path):
    url, state = http_service
    ledger = StateFile(tmp_path / "state.json")
    client = HttpClient(url, state=ledger)
    state["faults"][("POST", "/api/v2/value")] = [503]
    assert client.request("POST", "/value", {}, identity="same-key") == {"value": "ok"}
    assert state["calls"][("POST", "/api/v2/value")] == 2
    saved_key = next(iter(ledger.data["keys"].values()))
    assert saved_key in StateFile(tmp_path / "state.json").data["keys"].values()
    with pytest.raises(ToolError, match="different content"):
        client.request("POST", "/value", {"other": True}, identity="same-key")
    state["faults"][("POST", "/api/v2/value")] = [503]
    with pytest.raises(ToolError, match="1 attempts"):
        client.request("POST", "/value", {})


def test_unconfirmed_creation_is_not_repeated(http_service, tmp_path):
    url, state = http_service
    ledger = StateFile(tmp_path / "state.json")
    client = HttpClient(url, state=ledger)
    state["faults"][("POST", "/api/v2/workflows")] = [500]
    with pytest.raises(ToolError):
        seed_demo.ensure_resource(client, ledger, "workflow", "/workflows", {})
    with pytest.raises(ToolError, match="Unconfirmed"):
        seed_demo.ensure_resource(client, ledger, "workflow", "/workflows", {})
    assert state["calls"][("POST", "/api/v2/workflows")] == 1


def test_demo_http_protocol_and_resume(http_service, tmp_path, capsys):
    url, state = http_service
    args = ["--base-url", url, "--state-file", str(tmp_path / "demo.json")]
    assert seed_demo.main(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert len(summary["runs"]) == 60
    assert len(summary["agent_ids"]) == 8
    assert state["calls"][("POST", "/api/v1/tasks")] == 6
    assert len(state["runs"]) == 60
    assert seed_demo.main(args) == 0
    assert len(state["runs"]) == 60


def test_load_http_protocol_and_bounded_clients(http_service, tmp_path, capsys):
    url, state = http_service
    assert (
        load_test.main(
            [
                "--base-url",
                url,
                "--clients",
                "1,4",
                "--runs-per-level",
                "2",
                "--state-file",
                str(tmp_path / "load.json"),
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert [level["accepted"] for level in summary["levels"]] == [2, 2]
    assert len(state["runs"]) == 4
    assert (tmp_path / "out/load-4.json").exists()


def test_cli_invalid_arguments_and_fault_guard(monkeypatch, capsys, tmp_path):
    for function, flags in (
        (load_test.main, ["--clients", "99"]),
        (generate_dataset.main, ["--profile", "bad"]),
        (seed_demo.main, ["--base-url", "file:///tmp"]),
        (fault_suite.main, ["--scenario", "bad"]),
    ):
        with pytest.raises(SystemExit) as exc:
            function(flags)
        assert exc.value.code == 2
    monkeypatch.delenv("ALLOW_FAULT_TESTS", raising=False)
    assert fault_suite.main(["--memory"]) == 1
    capsys.readouterr()
    monkeypatch.setenv("ALLOW_FAULT_TESTS", "true")
    assert fault_suite.main(["--memory", "--output", str(tmp_path / "faults")]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["scope"] == "MEMORY_SINK"
    assert "api_restart" in summary["unexecuted"]
    assert all(record["passed"] for record in summary["records"])


def test_report_preserves_raw_samples_and_refuses_synthetic(
    tmp_path, monkeypatch, capsys
):
    path = Path(__file__).resolve().parents[3] / "contracts/v2/examples.json"
    document = json.loads(path.read_text(encoding="utf-8"))["experiment_results"][0]
    inputs, output = tmp_path / "inputs", tmp_path / "output"
    inputs.mkdir()
    (inputs / "sample.json").write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(report_experiments, "_plots", lambda rows, output: None)
    assert (
        report_experiments.main(["--input", str(inputs), "--output", str(output)]) == 1
    )
    capsys.readouterr()
    # Synthetic markers are stripped only inside this unit test to exercise
    # the transformation. These values are never saved as measured evidence.
    for sample in document["samples"]:
        sample["metrics"].pop("extra", None)
    (inputs / "sample.json").write_text(json.dumps(document), encoding="utf-8")
    assert (
        report_experiments.main(["--input", str(inputs), "--output", str(output)]) == 0
    )
    assert (
        json.loads((output / "exports.json").read_text(encoding="utf-8"))[0]["samples"]
        == document["samples"]
    )
    assert (output / "results.csv").exists()


def test_sse_deduplicates_and_repairs_gaps():
    from io import BytesIO
    import time

    events = [
        {
            "seq": seq,
            "kind": "run.finished" if seq == 4 else "checkpoint.saved",
            "recorded_at": "2026-11-18T00:00:00Z",
        }
        for seq in range(2, 5)
    ]
    stream = BytesIO(
        b"".join(
            (
                "event: " + event["kind"] + "\ndata: " + json.dumps(event) + "\n\n"
            ).encode()
            for event in [events[0], events[0], events[2]]
        )
    )

    class Client:
        url = "http://localhost/api/v2"
        opener = None

        def request(self, method, path, **kwargs):
            if path.endswith("snapshot"):
                return {"seq": 1, "run": {"status": "RUNNING"}}
            return {"data": [events[1]]}

        def open(self, *args, **kwargs):
            return stream

    client = Client()
    client.opener = client
    result = consume_stream(client, "run", deadline=time.monotonic() + 5)
    assert result["last_seq"] == 4 and result["received_events"] == 3


def test_reconciliation_detects_stored_token_corruption(monkeypatch):
    from app.execution_v2 import reduce_journal

    path = Path(__file__).resolve().parents[3] / "contracts/v2/examples.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    projection = reduce_journal(events=fixture["journal"])
    closed = projection["closed_result"]
    corrupt = False

    class Client:
        url = "http://fake/api/v2"

        def __init__(self, *args):
            pass

        def request(self, method, path, **kwargs):
            if path.endswith("snapshot"):
                return {
                    "run": fixture["run"],
                    "seq": 25,
                    "projection_complete": True,
                    "nodes": projection["nodes"],
                    "spans": projection["spans"],
                    "links": projection["links"],
                    "event_count": len(closed["events"]),
                }
            if "/journal?" in path:
                return {"data": fixture["journal"]}
            if "/spans?" in path:
                rows = check_run._wire(closed["spans"])
                if corrupt:
                    rows[0]["input_tokens"] = 42
                return {"data": rows, "meta": {"total": len(rows)}}
            if "/events?" in path:
                rows = check_run._wire(closed["events"])
                return {"data": rows, "meta": {"total": len(rows)}}
            return {"span_count": 7, "error_count": 0}

    monkeypatch.setattr(check_run, "HttpClient", Client)
    assert check_run.check_run(Client(), fixture["run"]["run_id"])["checks"][
        "final_projection_content"
    ]
    corrupt = True
    with pytest.raises(ToolError, match="Token"):
        check_run.check_run(Client(), fixture["run"]["run_id"])


def test_fault_driver_failure_retains_completed_evidence(monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace

    class Client:
        def __init__(self, *args):
            pass

        def request(self, *args):
            return {"protocol_version": "2.0"}

    calls = []

    def scenario(**kwargs):
        calls.append(kwargs["name"])
        if len(calls) == 2:
            raise TimeoutError("Injected adapter failure")
        return {
            "scope": "REAL_SERVICE",
            "fault_point": "unit_test_callback",
            "passed": True,
            "checks": {"completed": True},
        }

    monkeypatch.setenv("ALLOW_FAULT_TESTS", "true")
    monkeypatch.setattr(fault_suite, "HttpClient", Client)
    monkeypatch.setattr(
        fault_suite.importlib,
        "import_module",
        lambda name: SimpleNamespace(run_scenario=scenario),
    )
    assert fault_suite.main(["--driver", "test_only", "--output", str(tmp_path)]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert len(summary["records"]) == 2
    assert summary["records"][0]["passed"]
    assert summary["records"][1]["error"] == "TimeoutError"
    assert (tmp_path / "fault-results.json").exists()
