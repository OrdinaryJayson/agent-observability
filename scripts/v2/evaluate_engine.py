"""Reproduce independent engine evidence. VIRTUAL cases are semantic checks."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import time
from uuid import uuid4

from _common import parser, run_cli
from fault_suite import make_context, memory_faults
from app.analysis_v2 import analyze_run
from app.execution_v2 import RealtimeClock, execute_workflow
from app.execution_v2.memory import MemorySink
from app.execution_v2.protocol import digest
from app.execution_v2.templates import workflow_templates


async def evaluate():
    records = []
    for name in (
        "parallel",
        "serial",
        "failure",
        "recovered",
        "pass",
        "fallback",
        "realtime",
        "cancel",
    ):
        definition = workflow_templates()[
            "research"
            if name in {"failure", "recovered"}
            else ("quality" if name in {"pass", "fallback"} else "parallel")
        ]
        if name in {"failure", "recovered"}:
            definition["nodes"][1]["config"].update(
                failure_probability=1 if name == "failure" else 0.5, max_retries=2
            )
        if name in {"pass", "fallback"}:
            definition["nodes"][2]["config"]["result"] = (
                "PASS" if name == "pass" else "FAIL"
            )
        start = time.monotonic()

        class CancelSink(MemorySink):
            async def control(self):
                if time.monotonic() - start >= 0.15:
                    self.cancel_requested = True
                return await super().control()

        sink = (
            CancelSink(str(uuid4())) if name == "cancel" else MemorySink(str(uuid4()))
        )
        context = make_context(sink)
        context["definition"], context["definition_hash"] = (
            deepcopy(definition),
            digest(definition),
        )
        context["config"]["seed"] = 1 if name == "recovered" else 42
        context["config"]["max_parallelism"] = 1 if name == "serial" else 4
        if name in {"realtime", "cancel"}:
            context["clock"], context["config"]["mode"] = RealtimeClock(), "REALTIME"
        await execute_workflow(context=context, sink=sink)
        elapsed = (time.monotonic() - start) * 1000
        result = sink.projection()["closed_result"]
        analysis = analyze_run(definition=definition, projection=result)
        records.append(
            {
                "case": name,
                "scope": "MEMORY_SINK",
                "time_basis": result["time_basis"],
                "seed": context["config"]["seed"],
                "config": context["config"],
                "definition": definition,
                "status": result["final_status"],
                "span_count": len(result["spans"]),
                "error_count": sum(
                    span["status"] == "ERROR" for span in result["spans"]
                ),
                "journal_seq": sink.last_seq,
                "logical_duration_ms": result["logical_duration_ms"],
                "host_elapsed_ms": elapsed,
                "analysis": analysis,
                "nodes": [
                    {key: item[key] for key in ("node_key", "state", "attempt_no")}
                    for item in result["nodes"]
                ],
            }
        )
    assert (
        next(item for item in records if item["case"] == "parallel")[
            "logical_duration_ms"
        ]
        == 600
    )
    assert (
        next(item for item in records if item["case"] == "serial")[
            "logical_duration_ms"
        ]
        == 900
    )
    assert (
        next(item for item in records if item["case"] == "recovered")["status"]
        == "SUCCESS"
    )
    assert (
        next(item for item in records if item["case"] == "recovered")["error_count"] > 0
    )
    assert (
        next(item for item in records if item["case"] == "failure")["status"]
        == "FAILED"
    )
    assert (
        next(item for item in records if item["case"] == "cancel")["status"]
        == "CANCELLED"
    )
    return records, await memory_faults()


def action(args, summary):
    records, faults = asyncio.run(evaluate())
    args.output.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    evidence = {
        "scope": "INDEPENDENT_ENGINE",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_revision": revision,
        "cases": records,
        "faults": faults,
        "source_manifest": {
            str(path.resolve().relative_to(Path.cwd())).replace(
                "\\", "/"
            ): hashlib.sha256(
                path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()
            ).hexdigest()
            for directory in (
                Path("backend/app/execution_v2"),
                Path("backend/app/analysis_v2"),
                Path("scripts/v2"),
            )
            for path in sorted(directory.glob("*.py"))
        },
        "limitations": [
            "MemorySink does not prove PostgreSQL or cross-process durability.",
            "VIRTUAL durations are semantic checks, not host performance measurements.",
        ],
    }
    (args.output / "engine-evidence.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (args.output / "environment.json").write_text(
        json.dumps(
            {
                "os": platform.platform(),
                "python": platform.python_version(),
                "logical_cpu_count": os.cpu_count(),
                "memory_bytes": None,
                "disk_type": "unknown",
                "postgres_v2": "not integrated",
                "scope": "INDEPENDENT_ENGINE",
                "code_revision": revision,
                "plotting_tool": "matplotlib 3.10.7 (optional report command)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    summary.update(
        cases=len(records), memory_faults=len(faults), output=str(args.output)
    )


def main(argv=None):
    cli = parser(__doc__)
    cli.add_argument("--output", type=Path, default=Path("reports/v2"))
    return run_cli(action, cli.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
