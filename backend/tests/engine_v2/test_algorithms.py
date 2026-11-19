from copy import deepcopy
from datetime import datetime, timedelta, timezone
import random

import pytest

from app.analysis_v2.algorithms import (
    compare_runs,
    critical_path,
    robust_anomaly,
    self_times,
)
from app.execution_v2.templates import load_workflow, workflow_templates
from app.execution_v2.validation import validate_workflow
from test_engine import execute


@pytest.mark.parametrize(
    "mutation",
    [
        "cycle",
        "orphan",
        "duplicate",
        "role",
        "route",
        "config",
        "nan",
        "nul",
        "boolean",
        "budget",
    ],
)
def test_invalid_workflows(mutation):
    definition = workflow_templates()["parallel"]
    if mutation == "cycle":
        definition["edges"].append(
            {"source": "merge", "target": "search_a", "route": "ALWAYS"}
        )
    elif mutation == "orphan":
        definition["edges"] = [
            edge for edge in definition["edges"] if edge["target"] != "search_a"
        ]
    elif mutation == "duplicate":
        definition["nodes"].append(deepcopy(definition["nodes"][1]))
    elif mutation == "role":
        definition["nodes"][1]["role_key"] = "missing"
    elif mutation == "route":
        definition["edges"][0]["route"] = "PASS"
    elif mutation == "config":
        definition["nodes"][1]["config"]["sql"] = "anything"
    elif mutation == "nan":
        definition["nodes"][1]["config"]["failure_probability"] = float("nan")
    elif mutation == "nul":
        definition["nodes"][1]["name"] = "bad\0name"
    elif mutation == "boolean":
        definition["nodes"][1]["config"]["max_retries"] = True
    else:
        definition = load_workflow()
        for node in definition["nodes"]:
            if "duration_ms" in node["config"]:
                node["config"].update(duration_ms=1500, max_retries=2)
    report = validate_workflow(definition)
    assert report["valid"] is False
    assert all(
        set(error) == {"code", "node_key", "edge_index", "path", "message"}
        for error in report["errors"]
    )


def test_reachable_merge_is_insufficient_when_a_branch_bypasses_it():
    definition = workflow_templates()["quality"]
    definition["nodes"].insert(
        -1,
        {
            "node_key": "bypass",
            "name": "Bypass",
            "type": "TOOL",
            "role_key": None,
            "config": {"duration_ms": 100, "failure_probability": 0, "max_retries": 0},
        },
    )
    definition["nodes"].insert(
        -1,
        {
            "node_key": "outer",
            "name": "Outer",
            "type": "MERGE",
            "role_key": None,
            "config": {},
        },
    )
    definition["edges"] = [
        edge for edge in definition["edges"] if edge["target"] != "end"
    ] + [
        {"source": "accept", "target": "bypass", "route": "ALWAYS"},
        {"source": "bypass", "target": "outer", "route": "ALWAYS"},
        {"source": "merge", "target": "outer", "route": "ALWAYS"},
        {"source": "outer", "target": "end", "route": "ALWAYS"},
    ]
    assert validate_workflow(definition)["valid"] is False


def test_critical_path_against_independent_path_enumeration_oracle():
    rng = random.Random(22)
    for _ in range(50):
        keys = [f"node_{index}" for index in range(6)]
        edges = [
            {"source": keys[index], "target": keys[index + 1], "route": "ALWAYS"}
            for index in range(5)
        ]
        edges += [
            {"source": keys[left], "target": keys[right], "route": "ALWAYS"}
            for left in range(6)
            for right in range(left + 2, 6)
            if rng.random() < 0.25
        ]
        definition = {"nodes": [{"node_key": key} for key in keys], "edges": edges}
        weights = {key: rng.randint(0, 20) for key in keys}

        def enumerate_paths(key):
            successors = [edge["target"] for edge in edges if edge["source"] == key]
            if not successors:
                return [[key]]
            return [
                [key, *suffix]
                for successor in successors
                for suffix in enumerate_paths(successor)
            ]

        expected = max(
            sum(weights[key] for key in path) for path in enumerate_paths(keys[0])
        )
        result = critical_path(definition, weights, set(keys), {})
        assert result["duration_ms"] == expected
        assert sum(weights[key] for key in result["node_keys"]) == expected


def test_interval_union_clipping_zero_and_invalid_intervals():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def span(identity, parent, start, end):
        return {
            "span_id": identity,
            "parent_span_id": parent,
            "start_time": base + timedelta(milliseconds=start),
            "end_time": base + timedelta(milliseconds=end),
        }

    spans = [
        span("root", None, 0, 100),
        span("a", "root", -10, 60),
        span("b", "root", 20, 80),
        span("c", "root", 90, 150),
        span("zero", "root", 40, 40),
    ]
    assert self_times(spans)[0]["duration_ms"] == pytest.approx(10)
    spans[1]["end_time"] = None
    assert self_times(spans)[0]["duration_ms"] is None
    spans = [span("root", None, 10, 0)]
    assert self_times(spans)[0]["duration_ms"] is None


def test_comparison_keeps_missing_branch_null_and_rejects_other_modes():
    definition = workflow_templates()["quality"]
    definition["nodes"][2]["config"]["result"] = "SEEDED"
    results = [execute(definition, seed=seed)[1] for seed in (1, 2)]
    inputs = [
        {
            "run_id": f"run-{index}",
            "version_id": "same",
            "definition": definition,
            "projection": result,
        }
        for index, result in enumerate(results)
    ]
    comparison = compare_runs(inputs=inputs)
    for row in comparison["node_rows"]:
        for run in row["per_run"]:
            if run["state"] == "SKIPPED":
                assert run["duration_ms"] is None
    for projection in results:
        for span in projection["spans"]:
            if span["operation_type"] == "LLM":
                span["input_tokens"] = None
    unknown = compare_runs(inputs=inputs)
    assert all(
        item["input_tokens"] is None
        for row in unknown["node_rows"]
        for item in row["per_run"]
    )
    inputs[1]["projection"]["time_basis"] = "REALTIME"
    with pytest.raises(ValueError, match="clock"):
        compare_runs(inputs=inputs)
    inputs[1]["projection"]["time_basis"] = "VIRTUAL"
    inputs[1]["version_id"] = "other"
    with pytest.raises(ValueError, match="version"):
        compare_runs(inputs=inputs)


def test_mad_baseline_limits_and_zero_dispersion():
    assert robust_anomaly([1] * 19, 1000)["code"] == "INSUFFICIENT_BASELINE"
    assert robust_anomaly([10] * 20, 111)["anomalous"] is True
    assert robust_anomaly([10] * 20, 110)["anomalous"] is False
    assert robust_anomaly(list(range(20)), 1000)["anomalous"] is True
    with pytest.raises(ValueError):
        robust_anomaly([float("inf")] * 20, 5)


def test_load_workflow_has_twenty_nodes_and_four_parallel_branches():
    definition = load_workflow()
    assert len(definition["nodes"]) == 20
    assert validate_workflow(definition)["valid"]
    assert execute(definition)[1]["logical_duration_ms"] == 500
