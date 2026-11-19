"""Dependency critical paths, interval-union self time and comparable-run analysis."""

import math
from statistics import median

from app.execution_v2.protocol import EngineError, digest, mapping, timestamp, value
from app.execution_v2.validation import (
    OPERATIONS,
    graph,
    topological,
    validate_workflow,
)


def interval_union_ms(intervals: list[tuple]) -> float:
    ordered = sorted((timestamp(start), timestamp(end)) for start, end in intervals)
    if any(end < start for start, end in ordered):
        raise ValueError("Negative time interval")
    total = 0.0
    left = right = None
    for start, end in ordered:
        if right is None or start > right:
            if right is not None:
                total += (right - left).total_seconds() * 1000
            left, right = start, end
        else:
            right = max(right, end)
    if right is not None:
        total += (right - left).total_seconds() * 1000
    return total


def _duration(span) -> float:
    start, end = timestamp(span["start_time"]), timestamp(span["end_time"])
    if end < start:
        raise ValueError("Negative span interval")
    return (end - start).total_seconds() * 1000


def self_times(spans: list[dict]) -> list[dict]:
    children = {}
    for span in spans:
        children.setdefault(span["parent_span_id"], []).append(span)
    output = []
    for span in spans:
        try:
            start, end = timestamp(span["start_time"]), timestamp(span["end_time"])
            duration = _duration(span)
            intervals = []
            for child in children.get(span["span_id"], []):
                child_start, child_end = (
                    timestamp(child["start_time"]),
                    timestamp(child["end_time"]),
                )
                if child_end < child_start:
                    raise ValueError("Invalid child interval")
                if child_start < end and child_end > start:
                    intervals.append((max(start, child_start), min(end, child_end)))
            duration -= interval_union_ms(intervals)
        except (ValueError, TypeError, KeyError):
            duration = None
        output.append({"span_id": span["span_id"], "duration_ms": duration})
    return output


def critical_path(
    definition: dict, weights: dict[str, float], selected: set[str], routes: dict
) -> dict:
    nodes, incoming, outgoing = graph(definition)
    order = topological(nodes, incoming, outgoing)
    distance, previous = {}, {}
    for key in order:
        if key not in selected:
            continue
        candidates = [
            edge["source"]
            for edge in incoming[key]
            if edge["source"] in distance
            and (
                edge["route"] == "ALWAYS" or routes.get(edge["source"]) == edge["route"]
            )
        ]
        predecessor = (
            max(candidates, key=lambda item: (distance[item], item))
            if candidates
            else None
        )
        previous[key] = predecessor
        distance[key] = weights.get(key, 0) + (
            distance[predecessor] if predecessor else 0
        )
    if not distance:
        return {"node_keys": [], "duration_ms": 0}
    ranks = {key: index for index, key in enumerate(order)}
    current = max(distance, key=lambda item: (distance[item], ranks[item]))
    duration, path = distance[current], []
    while current is not None:
        path.append(current)
        current = previous[current]
    return {"node_keys": list(reversed(path)), "duration_ms": duration}


def robust_anomaly(
    samples: list[float], observed: float, *, absolute_threshold_ms=100
) -> dict:
    if any(
        type(number) not in (int, float) or not math.isfinite(number) or number < 0
        for number in [*samples, observed]
    ):
        raise ValueError("Anomaly inputs must be finite nonnegative durations")
    if len(samples) < 20:
        return {"code": "INSUFFICIENT_BASELINE", "anomalous": None, "n": len(samples)}
    center = median(samples)
    mad = median(abs(sample - center) for sample in samples)
    threshold = (
        max(absolute_threshold_ms, 3 * 1.4826 * mad) if mad else absolute_threshold_ms
    )
    return {
        "code": "ROBUST_DURATION",
        "anomalous": observed > center + threshold,
        "n": len(samples),
        "median_ms": center,
        "mad_ms": mad,
        "threshold_ms": threshold,
        "observed_ms": observed,
    }


def analyze_run(
    *, definition: dict, projection, algorithm_version: str = "2.0"
) -> dict:
    if algorithm_version != "2.0":
        raise ValueError("Unsupported algorithm version")
    if not validate_workflow(definition)["valid"]:
        raise ValueError("Invalid workflow definition")
    projection = mapping(projection)
    if projection["final_status"] not in {"SUCCESS", "FAILED", "CANCELLED"}:
        raise ValueError("Analysis requires a terminal projection")
    spans = projection["spans"]
    nodes = {node["node_key"]: node for node in projection["nodes"]}
    roots = [span for span in spans if span["parent_span_id"] is None]
    root_attributes = roots[0]["attributes"] if roots else {}
    weights, routes = {}, {}
    retry, scheduler = 0.0, 0.0
    errors = []
    for span in spans:
        attributes = span["attributes"]
        key = attributes.get("node_key")
        if key is None:
            continue
        duration = _duration(span)
        delay = attributes.get("retry_delay_ms", 0)
        # Backoff precedes the retry span, so it is added exactly once.
        if span["operation_type"] in OPERATIONS:
            weights[key] = weights.get(key, 0) + duration + delay
        if attributes.get("result") is not None:
            routes[key] = attributes["result"]
        if span["status"] == "ERROR":
            retry += duration
            errors.append(key)
        retry += delay
        if attributes.get("ready_at"):
            wait = (
                timestamp(span["start_time"]) - timestamp(attributes["ready_at"])
            ).total_seconds() * 1000
            if wait < 0:
                raise ValueError("Node starts before it is ready")
            scheduler += wait
    selected = {
        key
        for key, node in nodes.items()
        if node["state"] != "SKIPPED" and node["span_ids"]
    }
    path = critical_path(definition, weights, selected, routes)
    self_values = self_times(spans)
    findings = []
    if path["node_keys"]:
        findings.append(
            {
                "code": "DEPENDENCY_CRITICAL_PATH",
                "severity": "INFO",
                "node_keys": path["node_keys"],
                "evidence": {"duration_ms": path["duration_ms"]},
                "explanation": "Theoretical selected-DAG lower bound excludes container overlap and capacity delays.",
            }
        )
    if errors:
        findings.append(
            {
                "code": "FAILED_ATTEMPTS",
                "severity": "WARN",
                "node_keys": sorted(set(errors)),
                "evidence": {
                    "failed_attempts": len(errors),
                    "retry_overhead_ms": retry,
                },
                "explanation": "Cumulative failed work and backoff may exceed elapsed wall time.",
            }
        )
    return {
        "algorithm_version": algorithm_version,
        "journal_seq": root_attributes.get("journal_seq", 0),
        "time_basis": projection["time_basis"],
        "critical_path": path,
        "self_times": self_values,
        "retry_overhead_ms": retry,
        "scheduler_wait_ms": scheduler,
        "recovery_pause_ms": interval_union_ms(
            root_attributes.get("recovery_intervals", [])
        ),
        "findings": findings,
        "limitations": [
            "Critical path is a dependency estimate, not measured wall time or a causal attribution.",
            "Recovery pause is an observable journal interval estimate, not CPU downtime.",
            "Simulated Token counts and VIRTUAL durations do not measure model or host performance.",
            "INSUFFICIENT_BASELINE",
            *(
                ["SELF_TIME_UNAVAILABLE"]
                if any(item["duration_ms"] is None for item in self_values)
                else []
            ),
        ],
    }


def _known_tokens(spans, field):
    values = [span[field] for span in spans if span[field] is not None]
    return sum(values) if values else None


def compare_runs(*, inputs: list) -> dict:
    if not 2 <= len(inputs) <= 5:
        raise ValueError("Compare 2–5 terminal runs")
    run_ids = [str(value(item, "run_id")) for item in inputs]
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("Run IDs must be distinct")
    versions = {str(value(item, "version_id")) for item in inputs}
    projections = [mapping(value(item, "projection")) for item in inputs]
    definitions = [value(item, "definition") for item in inputs]
    if (
        len(versions) != 1
        or "None" in versions
        or len({digest(item) for item in definitions}) != 1
    ):
        raise ValueError("Runs must have the same immutable workflow version")
    modes = {item["time_basis"] for item in projections}
    if len(modes) != 1 or not modes <= {"REALTIME", "VIRTUAL"}:
        raise ValueError("Runs must have the same supported clock mode")
    summaries, node_rows = [], []
    for run_id, projection in zip(run_ids, projections):
        if projection["final_status"] not in {"SUCCESS", "FAILED", "CANCELLED"}:
            raise EngineError("CONFLICT", "Comparison requires terminal runs")
        root = next(
            (span for span in projection["spans"] if span["parent_span_id"] is None),
            None,
        )
        summaries.append(
            {
                "run_id": run_id,
                "execution_duration_ms": _duration(root) if root else 0,
                "input_tokens": sum(
                    span["input_tokens"] or 0
                    for span in projection["spans"]
                    if span["operation_type"] == "LLM"
                ),
                "output_tokens": sum(
                    span["output_tokens"] or 0
                    for span in projection["spans"]
                    if span["operation_type"] == "LLM"
                ),
                "status": projection["final_status"],
            }
        )
    for node in definitions[0]["nodes"]:
        key = node["node_key"]
        per_run = []
        for run_id, projection in zip(run_ids, projections):
            state = next(
                (
                    item["state"]
                    for item in projection["nodes"]
                    if item["node_key"] == key
                ),
                "SKIPPED",
            )
            spans = [
                span
                for span in projection["spans"]
                if span["attributes"].get("node_key") == key
            ]
            per_run.append(
                {
                    "run_id": run_id,
                    "state": state,
                    "attempt_count": len(spans),
                    "duration_ms": sum(_duration(span) for span in spans)
                    if spans
                    else None,
                    "input_tokens": _known_tokens(spans, "input_tokens")
                    if node["type"] == "LLM" and spans
                    else None,
                    "output_tokens": _known_tokens(spans, "output_tokens")
                    if node["type"] == "LLM" and spans
                    else None,
                }
            )
        node_rows.append({"node_key": key, "per_run": per_run})
    first, last = (
        summaries[0]["execution_duration_ms"],
        summaries[-1]["execution_duration_ms"],
    )
    return {
        "run_ids": run_ids,
        "version_id": next(iter(versions)),
        "time_basis": next(iter(modes)),
        "summary_rows": summaries,
        "node_rows": node_rows,
        "deltas": {
            "execution_duration_ms": last - first,
            "execution_relative_change": (last - first) / first if first else None,
        },
    }
