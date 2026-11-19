"""Explicit MemorySink faults or operator-provided real-service fault drivers."""

import asyncio
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from _common import HttpClient, ToolError, parser, run_cli
from app.execution_v2 import (
    EngineError,
    VirtualClock,
    execute_workflow,
    seal_interrupted,
)
from app.execution_v2.memory import MemorySink
from app.execution_v2.protocol import digest
from app.execution_v2.templates import workflow_templates

SCENARIOS = (
    "before_commit_disconnect",
    "commit_ack_lost",
    "api_restart",
    "worker_after_claim_crash",
    "parallel_worker_crash",
    "duplicate_recovery_claim",
    "old_worker_resurrection",
    "cancel_complete_race",
    "database_unavailable",
    "experiment_sql_timeout",
    "sse_reconnect",
)


class ManagedProcesses:
    """Only terminate handles created by this instance. Registry is an audit record."""

    def __init__(self, registry: Path):
        self.registry = registry
        self.processes = {}

    def start(self, name, command, *, cwd, env=None):
        if name in self.processes:
            raise ToolError("Process name is already registered")
        options = (
            {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        )
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **options,
        )
        self.processes[name] = process
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text(
            json.dumps({name: item.pid for name, item in self.processes.items()}),
            encoding="utf-8",
        )
        return process.pid

    def stop(self, name):
        process = self.processes[name]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def close(self):
        for name in self.processes:
            self.stop(name)


def make_context(sink):
    definition = workflow_templates()["parallel"]
    return {
        "run_id": sink.run_id,
        "trace_id": "a" * 32,
        "definition": definition,
        "definition_hash": digest(definition),
        "config": {"mode": "VIRTUAL", "unbound": True, "seed": 42},
        "agent_bindings": {},
        "lease_epoch": sink.lease_epoch,
        "last_seq": sink.last_seq,
        "checkpoint": deepcopy(sink.checkpoint),
        "clock": VirtualClock(),
    }


async def memory_faults():
    records = []
    for name, before, after in (
        ("before_commit_disconnect", 1, 0),
        ("commit_ack_lost", 0, 1),
        ("database_unavailable", 2, 0),
    ):
        sink = MemorySink(str(uuid4()))
        sink.fail_before_commit, sink.lose_ack = before, after
        await execute_workflow(context=make_context(sink), sink=sink)
        records.append(
            {
                "scenario": name,
                "scope": "MEMORY_SINK",
                "fault_point": "Sink.commit",
                "passed": sink.terminal["status"] == "SUCCESS",
                "checks": {
                    "unique_events": len(
                        {event["producer_event_id"] for event in sink.events}
                    )
                    == sink.last_seq
                },
            }
        )

    class CrashSink(MemorySink):
        async def commit(self, batch):
            ack = await super().commit(batch)
            if any(
                span["node_key"] == "search_b" for span in self.checkpoint["open_spans"]
            ):
                raise EngineError(
                    "LEASE_LOST", "Injected crash at committed parallel-start boundary"
                )
            return ack

    sink = CrashSink(str(uuid4()))
    try:
        await execute_workflow(context=make_context(sink), sink=sink)
    except EngineError:
        pass
    old_batch = deepcopy(sink.commit_calls[-1])
    sink.__class__ = MemorySink
    sealed = seal_interrupted(
        events=sink.events, reason="WorkerLost", ended_at=sink.deadline_at
    )
    records.append(
        {
            "scenario": "worker_after_claim_crash",
            "scope": "MEMORY_SINK",
            "fault_point": "Persisted open attempt",
            "passed": sealed["final_status"] == "FAILED",
            "checks": {
                "sealed_open_attempts": all(
                    span["end_time"] is not None for span in sealed["spans"]
                )
            },
        }
    )
    sink.recover()
    old_batch["batch_id"] = str(uuid4())
    rejected = False
    try:
        await sink.commit(old_batch)
    except EngineError as exc:
        rejected = exc.code == "LEASE_LOST"
    records.append(
        {
            "scenario": "old_worker_resurrection",
            "scope": "MEMORY_SINK",
            "fault_point": "Old epoch before new write",
            "passed": rejected,
            "checks": {"fenced": rejected},
        }
    )
    await execute_workflow(context=make_context(sink), sink=sink)
    records.append(
        {
            "scenario": "parallel_worker_crash",
            "scope": "MEMORY_SINK",
            "fault_point": "Checkpoint recovery",
            "passed": sink.terminal["status"] == "SUCCESS",
            "checks": {
                "worker_lost_preserved": any(
                    span["error_type"] == "WorkerLost"
                    for span in sink.projection()["closed_result"]["spans"]
                )
            },
        }
    )
    return records


def fault_suite(args, summary):
    if os.getenv("ALLOW_FAULT_TESTS", "").lower() != "true":
        raise ToolError(
            "Set ALLOW_FAULT_TESTS=true for the dedicated fault-test service"
        )
    selected = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    if args.memory:
        records = asyncio.run(memory_faults())
        records = [record for record in records if record["scenario"] in selected]
        summary.update(
            scope="MEMORY_SINK",
            records=records,
            unexecuted=[
                name
                for name in selected
                if name not in {record["scenario"] for record in records}
            ],
        )
    else:
        if not args.driver:
            raise ToolError(
                "Real faults require a B/operator driver with controlled service hooks and owned process handles"
            )
        client = HttpClient(args.base_url)
        capabilities = client.request("GET", "/capabilities")
        if capabilities["protocol_version"] != "2.0":
            raise ToolError("Fault target is not a v2 test service")
        driver = importlib.import_module(args.driver)
        with_registry = ManagedProcesses(args.output / "owned-processes.json")
        records = []
        try:
            for name in selected:
                beginning = time.monotonic()
                try:
                    record = driver.run_scenario(
                        name=name, client=client, processes=with_registry
                    )
                    if (
                        record.get("scope") != "REAL_SERVICE"
                        or not record.get("fault_point")
                        or not isinstance(record.get("checks"), dict)
                        or type(record.get("passed")) is not bool
                    ):
                        raise ToolError(
                            "Fault driver did not provide real-service fault/evidence metadata"
                        )
                except Exception as exc:
                    record = {
                        "scope": "REAL_SERVICE",
                        "fault_point": "driver_callback",
                        "passed": False,
                        "checks": {"driver_completed": False},
                        "error": type(exc).__name__,
                    }
                records.append(
                    record
                    | {
                        "scenario": name,
                        "elapsed_seconds": time.monotonic() - beginning,
                    }
                )
                if not record["passed"]:
                    break
        finally:
            with_registry.close()
        summary.update(
            scope="REAL_SERVICE",
            records=records,
            unexecuted=[
                name
                for name in selected
                if name not in {record["scenario"] for record in records}
            ],
        )
    args.output.mkdir(parents=True, exist_ok=True)
    passed = bool(summary["records"]) and all(
        record["passed"] and all(record["checks"].values())
        for record in summary["records"]
    )
    (args.output / "fault-results.json").write_text(
        json.dumps(summary | {"complete": passed}, indent=2), encoding="utf-8"
    )
    if not passed:
        raise ToolError("Fault correctness invariant failed")


def main(argv=None):
    cli = parser(__doc__)
    cli.add_argument("--scenario", choices=["all", *SCENARIOS], default="all")
    cli.add_argument("--memory", action="store_true")
    cli.add_argument(
        "--driver", help="Importable B/operator module exposing run_scenario"
    )
    cli.add_argument("--output", type=Path, default=Path("backend/var/v2/faults"))
    return run_cli(fault_suite, cli.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
