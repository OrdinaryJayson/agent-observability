"""Create eight Agents, three published scenarios and sixty business-API runs."""

from pathlib import Path

from _common import HttpClient, StateFile, ToolError, parser, run_cli
from _datasets import GENERATOR_VERSION
from app.execution_v2.protocol import digest
from app.execution_v2.templates import workflow_templates


def ensure_resource(client, state, label, path, body, *, headers=None):
    saved = state.resource(label)
    if saved is not None:
        return saved
    pending = state.data.setdefault("pending_posts", {})
    if label in pending:
        raise ToolError(
            f"Unconfirmed non-idempotent POST for {label}. Reconcile the saved path/body before resuming."
        )
    pending[label] = {"path": path, "body": body}
    state.save()
    resource = client.request("POST", path, body, headers=headers)
    state.resource(label, resource)
    del pending[label]
    state.save()
    return resource


def publish(client, state, label, definition):
    workflow = ensure_resource(
        client,
        state,
        label,
        "/workflows",
        {
            "name": f"DEMO_V2 {label}",
            "description": "Seeded course demonstration",
            "draft": definition,
        },
    )
    validation = client.request(
        "POST", f"/workflows/{workflow['workflow_id']}/validate", {"draft": definition}
    )
    if not validation["valid"]:
        raise ToolError("Server rejected the generated workflow")
    return ensure_resource(
        client,
        state,
        label + ":version",
        f"/workflows/{workflow['workflow_id']}/versions",
        {"expected_definition_hash": digest(definition)},
        headers={"If-Match": f'"{workflow["revision"]}"'},
    )


def seed_demo(args, summary):
    state = StateFile(args.state_file)
    state.bind({"base_url": args.base_url, "seed": args.seed, "profile": args.profile})
    summary.update(path="BUSINESS_HTTP", state_file=args.state_file)
    v2 = HttpClient(args.base_url, state=state)
    v1 = HttpClient(args.base_url.removesuffix("/api/v2") + "/api/v1", state=state)
    roles = [
        "researcher",
        "analyst",
        "reviewer",
        "writer",
        "retriever",
        "validator",
        "planner",
        "editor",
    ]
    agents = {}
    for role in roles:
        agents[role] = ensure_resource(
            v1,
            state,
            "agent:" + role,
            "/agents",
            {
                "name": f"DEMO_V2 {role}",
                "role": role,
                "provider": "simulated",
                "model_name": "mock-v2",
            },
        )["agent_id"]
    templates = workflow_templates()
    templates["research"]["nodes"][1]["config"]["failure_probability"] = 0.35
    templates["quality"]["nodes"][2]["config"]["result"] = "SEEDED"
    versions = {
        key: publish(v2, state, key, definition)
        for key, definition in templates.items()
    }
    dataset = ensure_resource(
        v2,
        state,
        "dataset",
        "/datasets",
        {
            "name": "DEMO_V2",
            "purpose": "DEMO",
            "seed": args.seed,
            "config": {"profile": "DEMO_V2"},
            "generator_version": GENERATOR_VERSION,
        },
    )
    summary.update(
        dataset_id=dataset["dataset_id"],
        agent_ids=agents,
        version_ids={key: item["version_id"] for key, item in versions.items()},
        runs=[],
    )
    counts = {"runs": 0, "spans": 0}
    logical_records = []
    for index in range(60):
        task = ensure_resource(
            v1,
            state,
            f"task:{index // 10}",
            "/tasks",
            {"title": f"DEMO_V2 task {index // 10}", "scenario_type": "GENERAL"},
        )
        name = "research" if index < 30 else ("parallel" if index < 45 else "quality")
        request = {
            "version_id": versions[name]["version_id"],
            "agent_bindings": {
                role["role_key"]: agents[role["role_key"]]
                for role in templates[name]["roles"]
            },
            "unbound": False,
            "seed": args.seed + index,
            "mode": "REALTIME",
            "max_parallelism": 4,
            "priority": 0,
            "retry_of_run_id": None,
            "dataset_id": dataset["dataset_id"],
        }
        run = v2.request(
            "POST", f"/tasks/{task['task_id']}/runs", request, identity=f"demo-{index}"
        )
        state.resource(f"run:{index}", run)
        summary["runs"].append(run["run_id"])
        if index in {58, 59}:
            v2.request("POST", f"/runs/{run['run_id']}/cancel", {})
        completed = v2.poll(f"/runs/{run['run_id']}", timeout=610)
        snapshot = v2.request("GET", f"/runs/{run['run_id']}/snapshot")
        if not snapshot["projection_complete"]:
            raise ToolError("Demo run has incomplete terminal projection")
        counts["runs"] += 1
        counts["spans"] += len(snapshot["spans"])
        logical_records.append(
            {
                "ordinal": index,
                "status": completed["status"],
                "nodes": [
                    {key: node[key] for key in ("node_key", "state", "attempt_no")}
                    for node in snapshot["nodes"]
                ],
                "attempts": [
                    {
                        key: span.get(key)
                        for key in (
                            "node_key",
                            "role_key",
                            "attempt_no",
                            "state",
                            "operation_type",
                            "input_tokens",
                            "output_tokens",
                            "error_type",
                        )
                    }
                    for span in snapshot["spans"]
                ],
            }
        )
        summary.setdefault("statuses", {}).setdefault(completed["status"], 0)
        summary["statuses"][completed["status"]] += 1
    finalized = v2.request(
        "POST",
        f"/datasets/{dataset['dataset_id']}/finalize",
        {
            "actual_counts": counts,
            "content_hash": digest(
                {
                    "generator_version": GENERATOR_VERSION,
                    "seed": args.seed,
                    "templates": templates,
                    "records": logical_records,
                }
            ),
        },
    )
    if finalized["state"] != "READY":
        raise ToolError("Demo manifest was not finalized READY")
    summary.update(actual_counts=counts, persisted=True)


def main(argv=None):
    cli = parser(__doc__)
    cli.add_argument("--seed", type=int, default=42)
    cli.add_argument("--profile", choices=["full"], default="full")
    cli.add_argument(
        "--state-file", default=str(Path("backend/var/v2/demo-state.json"))
    )
    return run_cli(seed_demo, cli.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
