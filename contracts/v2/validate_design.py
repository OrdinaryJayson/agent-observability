"""Validate design artifacts, linked examples and deliberately invalid inputs."""

import copy
import importlib.util
import json
import re
import tempfile
from collections import deque
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def semantic_graph(value):
    nodes = {item["node_key"]: item for item in value["nodes"]}
    assert len(nodes) == len(value["nodes"]), "duplicate node"
    roles = {item["role_key"] for item in value["roles"]}
    assert len(roles) == len(value["roles"]), "duplicate role"
    assert all(item["role_key"] is None or item["role_key"] in roles for item in nodes.values()), "missing role"
    starts = [key for key, item in nodes.items() if item["type"] == "START"]
    ends = [key for key, item in nodes.items() if item["type"] == "END"]
    assert len(starts) == len(ends) == 1, "start/end cardinality"
    outgoing, incoming = {key: [] for key in nodes}, {key: [] for key in nodes}
    unique = set()
    for edge in value["edges"]:
        source, target, route = edge["source"], edge["target"], edge["route"]
        assert source in nodes and target in nodes and source != target, "invalid edge"
        key = source, target, route
        assert key not in unique, "duplicate edge"
        unique.add(key)
        outgoing[source].append((target, route))
        incoming[target].append(source)
    assert not incoming[starts[0]] and not outgoing[ends[0]], "start/end direction"
    for key, item in nodes.items():
        assert item["type"] == "MERGE" or len(incoming[key]) <= 1, "multiple inputs require MERGE"
        routes = [route for _, route in outgoing[key]]
        if item["type"] == "CONDITION":
            assert sorted(routes) == ["FAIL", "PASS"], "condition routes"
        else:
            assert all(route == "ALWAYS" for route in routes), "ordinary edge route"
    degree = {key: len(items) for key, items in incoming.items()}
    ready = deque(key for key, count in degree.items() if not count)
    visited = []
    while ready:
        key = ready.popleft()
        visited.append(key)
        for target, _ in outgoing[key]:
            degree[target] -= 1
            if degree[target] == 0:
                ready.append(target)
    assert len(visited) == len(nodes), "cycle"

    def reach(first, adjacency):
        seen, pending = set(), [first]
        while pending:
            key = pending.pop()
            if key not in seen:
                seen.add(key)
                pending.extend(adjacency[key])
        return seen

    forward = {key: [target for target, _ in edges] for key, edges in outgoing.items()}
    assert len(reach(starts[0], forward)) == len(nodes), "unreachable node"
    assert len(reach(ends[0], incoming)) == len(nodes), "cannot reach end"
    for key, item in nodes.items():
        if item["type"] == "CONDITION":
            left, right = [target for target, _ in outgoing[key]]
            common = reach(left, forward) & reach(right, forward)
            assert any(nodes[target]["type"] == "MERGE" for target in common), "branch merge missing"


def expect_rejected(callback, value):
    try:
        callback(value)
    except (AssertionError, ValidationError):
        return
    raise AssertionError("invalid fixture was accepted")


def main():
    spec = importlib.util.spec_from_file_location("v2_design_builder", ROOT / "build_examples.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    with tempfile.TemporaryDirectory(prefix="v2-design-") as directory:
        builder.ROOT = Path(directory)
        builder.schemas()
        builder.artifacts()
        for name in ("workflow.schema.json", "journal-batch.schema.json", "examples.json", "http-manifest.json"):
            assert (ROOT / name).read_bytes() == (Path(directory) / name).read_bytes(), f"rebuild {name}"
    workflow_schema, batch_schema = load("workflow.schema.json"), load("journal-batch.schema.json")
    for schema in (workflow_schema, batch_schema):
        Draft202012Validator.check_schema(schema)
    wf = Draft202012Validator(workflow_schema, format_checker=FormatChecker())
    batch = Draft202012Validator(batch_schema, format_checker=FormatChecker())
    examples = load("examples.json")
    for definition in examples["workflow_definitions"].values():
        wf.validate(definition)
        semantic_graph(definition)
    for value in examples["journal_batches"]:
        batch.validate(value)
        assert value["checkpoint"]["journal_seq"] == value["expected_last_seq"]
        assert len(json.dumps(value).encode()) <= 512 * 1024
    journal, spans, events = examples["journal"], {}, {}
    assert [item["seq"] for item in journal] == list(range(1, len(journal) + 1))
    assert len({item["producer_event_id"] for item in journal}) == len(journal)
    for item in journal:
        data = item["payload"]
        if item["kind"] == "span.started":
            assert data["span_id"] not in spans
            if data["parent_span_id"]:
                assert data["parent_span_id"] in spans
            spans[data["span_id"]] = {**data, "state": "RUNNING"}
        elif item["kind"] == "span.finished":
            span = spans[data["span_id"]]
            assert span["state"] == "RUNNING"
            if span["operation_type"] != "LLM":
                assert data["input_tokens"] is data["output_tokens"] is None
            span.update(data, state=data["status"])
        elif item["kind"] == "span.event":
            assert data["span_id"] in spans and data["event_id"] not in events
            events[data["event_id"]] = data
        elif item["kind"] == "link.created":
            assert data["source_span_id"] in spans and data["target_span_id"] in spans
    assert len(spans) == examples["run"]["span_count"] == len(examples["snapshot"]["spans"])
    assert all(item["state"] == "SUCCESS" for item in spans.values())
    assert sum(item["parent_span_id"] is None for item in spans.values()) == 1
    assert len(events) == examples["snapshot"]["event_count"]
    assert journal[-1]["kind"] == "run.finished"
    assert journal[-1]["seq"] == journal[-1]["payload"]["final_seq"] == examples["snapshot"]["seq"]
    assert examples["batch_acks"][-1]["last_seq"] == len(journal)
    for result in examples["experiment_results"]:
        assert result["experiment"]["sample_count"] == len(result["samples"])
        for trial in result["trials"]:
            samples = [sample for sample in result["samples"] if sample["trial_id"] == trial["trial_id"]]
            assert sum(not sample["is_warmup"] for sample in samples) == trial["summary"]["n"] == 15
            assert sum(sample["is_warmup"] for sample in samples) == 3
    invalid = copy.deepcopy(examples["workflow_definitions"]["parallel"])
    invalid["nodes"][1]["config"]["duration_ms"] = -1
    expect_rejected(wf.validate, invalid)
    invalid = copy.deepcopy(examples["workflow_definitions"]["parallel"])
    invalid["nodes"].append(copy.deepcopy(invalid["nodes"][0]))
    expect_rejected(semantic_graph, invalid)
    invalid = copy.deepcopy(examples["workflow_definitions"]["parallel"])
    invalid["edges"].append({"source": "merge", "target": "search_a", "route": "ALWAYS"})
    expect_rejected(semantic_graph, invalid)
    invalid = copy.deepcopy(examples["journal_batches"][0])
    invalid["events"][0]["kind"] = "run.finished"
    expect_rejected(batch.validate, invalid)
    invalid = copy.deepcopy(examples["journal_batches"][0])
    invalid["checkpoint"]["unexpected_field"] = True
    expect_rejected(batch.validate, invalid)
    manifest = load("http-manifest.json")
    routes = [(item["method"], item["path"]) for item in manifest["routes"]]
    assert len(set(routes)) == len(routes)
    assert all(not item["implemented"] for item in manifest["routes"])
    assert next(item for item in manifest["routes"] if item["path"].endswith("/analytics/refresh"))["success_status"] == 200
    checked_links = 0
    for path in [REPO / "README.md", *(REPO / "docs").glob("1[3-8]-*.md")]:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if "://" not in target and not target.startswith("#"):
                assert (path.parent / target.split("#")[0]).resolve().exists(), (path, target)
                checked_links += 1
    print(json.dumps({"schemas": 2, "valid_workflows": 3, "valid_batches": 2,
                      "journal_events": len(journal), "experiment_cases": len(examples["experiment_results"]),
                      "negative_checks": 5, "routes": len(routes), "local_links": checked_links,
                      "reproducible_artifacts": 4, "status": "passed", "scope": "design_only"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
