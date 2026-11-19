"""Bounded real-HTTP LOAD_V2 runs, idempotent acceptance and SSE observations."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time

from _common import HttpClient, StateFile, ToolError, parser, positive, run_cli
from _datasets import GENERATOR_VERSION
from _stream import consume_stream
from _resources import ResourceSampler
from seed_demo import ensure_resource, publish
from app.execution_v2.protocol import digest
from app.execution_v2.templates import load_workflow


def clients_arg(text):
    try:
        values = [int(item) for item in text.split(",")]
    except ValueError as exc:
        raise ValueError("Clients must be comma-separated integers") from exc
    if (
        not values
        or len(set(values)) != len(values)
        or any(item not in {1, 4, 8, 16} for item in values)
    ):
        raise ValueError("Clients must be a unique subset of 1,4,8,16")
    return values


def load_test(args, summary):
    state = StateFile(args.state_file)
    state.bind(
        {
            "base_url": args.base_url,
            "clients": args.clients,
            "runs": args.runs_per_level,
        }
    )
    v2 = HttpClient(args.base_url, state=state)
    v1 = HttpClient(args.base_url.removesuffix("/api/v2") + "/api/v1", state=state)
    definition = load_workflow()
    version = publish(v2, state, "load-20", definition)
    task = ensure_resource(
        v1,
        state,
        "load-task",
        "/tasks",
        {"title": "LOAD_V2", "scenario_type": "GENERAL"},
    )
    dataset = ensure_resource(
        v2,
        state,
        "load-dataset",
        "/datasets",
        {
            "name": "LOAD_V2",
            "purpose": "LOAD",
            "seed": 42,
            "config": {"profile": "LOAD_V2"},
            "generator_version": GENERATOR_VERSION,
        },
    )
    summary.update(
        path="REAL_HTTP_LOAD",
        dataset_id=dataset["dataset_id"],
        levels=[],
        state_file=args.state_file,
        resources={
            "database_connection_peak": None,
            "api_rss_peak_bytes": None,
            "reason": "Requires operator/B process-resource sampler. No public resource endpoint is defined.",
        },
    )
    args.output.mkdir(parents=True, exist_ok=True)
    all_samples = []
    for clients in args.clients:
        beginning = time.monotonic()
        measurement_start = time.perf_counter()
        deadline = beginning + 180
        samples = []
        resources = ResourceSampler(args.resource_driver)
        resources.start()

        def run(index):
            sample = {
                "clients": clients,
                "ordinal": index,
                "run_id": None,
                "accepted": False,
            }
            try:
                if time.monotonic() >= deadline:
                    raise ToolError("LOAD level deadline reached before acceptance")
                posted = time.perf_counter()
                run = v2.request(
                    "POST",
                    f"/tasks/{task['task_id']}/runs",
                    {
                        "version_id": version["version_id"],
                        "agent_bindings": {},
                        "unbound": True,
                        "mode": "REALTIME",
                        "seed": 42 + index,
                        "max_parallelism": 4,
                        "priority": 0,
                        "retry_of_run_id": None,
                        "dataset_id": dataset["dataset_id"],
                    },
                    identity=f"load-{clients}-{index}",
                    deadline=deadline,
                )
                sample.update(
                    run_id=run["run_id"],
                    accepted=True,
                    accept_ms=(time.perf_counter() - posted) * 1000,
                )
                state.resource(f"load-{clients}-{index}", run)
                sample["stream"] = consume_stream(v2, run["run_id"], deadline=deadline)
                finished = v2.request(
                    "GET", f"/runs/{run['run_id']}", deadline=deadline
                )
                sample.update(
                    status=finished["status"],
                    queue_ms=finished["queue_duration_ms"],
                    execution_ms=finished["execution_duration_ms"],
                    span_count=finished["span_count"],
                    business_failure=finished["status"] == "FAILED",
                    infrastructure_error=False,
                )
            except (ToolError, OSError, ValueError) as exc:
                sample.update(infrastructure_error=True, error=str(exc))
            return sample

        try:
            with ThreadPoolExecutor(max_workers=clients) as pool:
                for future in as_completed(
                    [pool.submit(run, index) for index in range(args.runs_per_level)]
                ):
                    samples.append(future.result())
        finally:
            resource_result = resources.finish()
        elapsed = time.perf_counter() - measurement_start
        samples.sort(key=lambda sample: sample["ordinal"])
        (args.output / f"load-{clients}.json").write_text(
            json.dumps(samples, indent=2), encoding="utf-8"
        )
        (args.output / f"resources-{clients}.json").write_text(
            json.dumps(resource_result, indent=2), encoding="utf-8"
        )
        completed = sum(
            sample.get("status") in {"SUCCESS", "FAILED", "CANCELLED"}
            for sample in samples
        )
        summary["levels"].append(
            {
                "clients": clients,
                "accepted": sum(sample["accepted"] for sample in samples),
                "completed": completed,
                "infrastructure_errors": sum(
                    sample["infrastructure_error"] for sample in samples
                ),
                "elapsed_seconds": elapsed,
                "completion_per_second": completed / elapsed if elapsed > 0 else None,
                "raw_samples": str(args.output / f"load-{clients}.json"),
                "resource_peaks": resource_result["peaks"],
            }
        )
        all_samples.extend(samples)
    if any(sample["infrastructure_error"] for sample in all_samples):
        raise ToolError(
            "LOAD includes infrastructure errors/timeouts. Raw samples and IDs were retained."
        )
    finalized = v2.request(
        "POST",
        f"/datasets/{dataset['dataset_id']}/finalize",
        {
            "actual_counts": {
                "runs": len(all_samples),
                "spans": sum(sample["span_count"] for sample in all_samples),
            },
            "content_hash": digest(
                {
                    "generator_version": GENERATOR_VERSION,
                    "definition": definition,
                    "records": [
                        {
                            key: sample[key]
                            for key in ("clients", "ordinal", "status", "span_count")
                        }
                        for sample in all_samples
                    ],
                }
            ),
        },
    )
    if finalized["state"] != "READY":
        raise ToolError("LOAD manifest was not finalized READY")


def main(argv=None):
    cli = parser(__doc__)
    cli.add_argument("--clients", type=clients_arg, default=[1, 4, 8, 16])
    cli.add_argument("--runs-per-level", type=positive, default=300)
    cli.add_argument("--state-file", default="backend/var/v2/load-state.json")
    cli.add_argument(
        "--resource-driver",
        help="B/operator read-only module exposing sample_resources()",
    )
    cli.add_argument("--output", type=Path, default=Path("backend/var/v2/load"))
    return run_cli(load_test, cli.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
