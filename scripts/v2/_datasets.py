"""Streaming legal offline clones for B's controlled Loader. No SQL access."""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import random
from uuid import NAMESPACE_URL, uuid5

from _common import ToolError
from app.execution_v2.protocol import encoded, iso, timestamp

GENERATOR_VERSION = "2.0-engine-1"
SIZES = {"BENCH_100K": 200, "BENCH_1M": 2000}


def stable_id(seed, kind, index):
    return str(uuid5(NAMESPACE_URL, f"agent-observability-v2:{seed}:{kind}:{index}"))


def iter_dataset(
    *,
    profile,
    seed=42,
    distribution="uniform",
    failure_rate=0.1,
    selectivity=0.01,
    payload_bytes=128,
):
    """Yield per-Run bundles. The Loader adapter maps these into its isolated tables.

    Each bundle has the existing five-table dictionaries and span_links. Offline
    clones are data fixtures, not executions of an oversized v2 workflow.
    """
    if profile not in SIZES or distribution not in {"uniform", "hotspot"}:
        raise ToolError("Unknown dataset profile/distribution")
    if (
        failure_rate not in {0.01, 0.1, 0.5}
        or selectivity not in {0.001, 0.01, 0.1, 0.5}
        or payload_bytes not in {128, 1024, 4096}
    ):
        raise ToolError("Unsupported frozen dataset distribution parameter")
    total = SIZES[profile] * 500
    selected_count = round(total * selectivity)
    rng = random.Random(seed)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    agents = [
        {
            "agent_id": stable_id(seed, "agent", index),
            "name": f"Entity {index}",
            "role": f"role_{index}",
            "provider": "simulated",
            "model_name": "mock-v2",
            "status": "ACTIVE",
            "created_at": iso(base),
        }
        for index in range(100)
    ]
    for run_index in range(SIZES[profile]):
        run_id = stable_id(seed, "run", run_index)
        task_id = stable_id(seed, "task", run_index // 10)
        started = base + timedelta(
            days=run_index * 90 // SIZES[profile], seconds=run_index % 100
        )
        ended = started + timedelta(seconds=2)
        spans, events, links = [], [], []
        role_entities = [
            rng.randrange(20)
            if distribution == "hotspot" and rng.random() < 0.8
            else rng.randrange(20 if distribution == "hotspot" else 0, 100)
            for _ in range(8)
        ]
        root_id = f"{1:016x}"
        failed = False
        for ordinal in range(500):
            role = (ordinal - 1) % 8 if ordinal else None
            operation = (
                "WORKFLOW"
                if ordinal == 0
                else (
                    "AGENT" if ordinal <= 8 else ("LLM" if ordinal % 3 == 0 else "TOOL")
                )
            )
            entity = (
                rng.randrange(20)
                if distribution == "hotspot" and rng.random() < 0.8
                else rng.randrange(20 if distribution == "hotspot" else 0, 100)
            )
            # Role identity remains stable inside a Run, including inherited children.
            if ordinal <= 8 and ordinal:
                entity = role_entities[role]
            agent = None if role is None else agents[role_entities[role]]["agent_id"]
            if operation not in {"WORKFLOW", "AGENT"}:
                agent = spans[role + 1]["agent_id"]
            parent = (
                None
                if ordinal == 0
                else (root_id if ordinal <= 8 else f"{role + 2:016x}")
            )
            begin = (
                started
                if ordinal <= 8
                else started + timedelta(milliseconds=ordinal % 100)
            )
            finish = (
                ended
                if ordinal <= 8
                else begin + timedelta(milliseconds=100 + ordinal % 1000)
            )
            is_error = ordinal > 8 and rng.random() < failure_rate
            failed |= is_error
            attributes = {
                "tool_category": f"tool_{entity:02d}",
                "region": "target"
                if run_index * 500 + ordinal < selected_count
                else "other",
                "payload_size": payload_bytes,
            }
            attributes["padding"] = ""
            attributes["padding"] = "x" * (payload_bytes - len(encoded(attributes)))
            span_id = f"{ordinal + 1:016x}"
            spans.append(
                {
                    "span_id": span_id,
                    "parent_span_id": parent,
                    "agent_id": agent,
                    "operation_type": operation,
                    "span_name": f"{operation} {ordinal}",
                    "status": "ERROR" if is_error else "SUCCESS",
                    "start_time": iso(begin),
                    "end_time": iso(finish),
                    "provider": "simulated" if operation == "LLM" else None,
                    "model_name": "mock-v2" if operation == "LLM" else None,
                    "tool_name": f"tool_{entity:02d}" if operation == "TOOL" else None,
                    "input_tokens": ordinal % 100 if operation == "LLM" else None,
                    "output_tokens": ordinal % 50 if operation == "LLM" else None,
                    "error_type": "SimulatedNodeError" if is_error else None,
                    "error_message": "Generated benchmark failure"
                    if is_error
                    else None,
                    "attributes": attributes,
                }
            )
            events.append(
                {
                    "event_id": stable_id(seed, "event", run_index * 500 + ordinal),
                    "span_id": span_id,
                    "event_name": "fixture.failed" if is_error else "fixture.completed",
                    "severity": "ERROR" if is_error else "INFO",
                    "message": "Offline benchmark fixture",
                    "occurred_at": iso(finish),
                    "attributes": {},
                }
            )
            if ordinal > 9:
                links.append(
                    {
                        "source_span_id": f"{ordinal:016x}",
                        "target_span_id": span_id,
                        "link_type": "DEPENDS_ON",
                    }
                )
        yield {
            "ordinal": run_index,
            "agents": agents if run_index == 0 else [],
            "tasks": [
                {
                    "task_id": task_id,
                    "title": f"Benchmark task {run_index // 10}",
                    "description": None,
                    "scenario_type": "GENERAL",
                    "created_at": iso(started),
                }
            ]
            if run_index % 10 == 0
            else [],
            "runs": [
                {
                    "run_id": run_id,
                    "task_id": task_id,
                    "trace_id": run_id.replace("-", ""),
                    "source_type": "SIMULATED",
                    "status": "FAILED" if failed else "SUCCESS",
                    "started_at": iso(started),
                    "ended_at": iso(ended),
                    "error_summary": "Generated benchmark failure" if failed else None,
                    "created_at": iso(started),
                }
            ],
            "spans": spans,
            "span_events": events,
            "span_links": links,
        }


def logical_bundle(bundle, agent_keys):
    """Exclude generated identities/timestamps, preserve logical ordering/references."""
    spans = []
    for span in bundle["spans"]:
        spans.append(
            {
                key: item
                for key, item in span.items()
                if key not in {"agent_id", "start_time", "end_time"}
            }
            | {"agent_entity": agent_keys.get(span["agent_id"])}
        )
    return {
        "ordinal": bundle["ordinal"],
        "spans": spans,
        "events": [
            {
                key: item
                for key, item in event.items()
                if key not in {"event_id", "occurred_at"}
            }
            for event in bundle["span_events"]
        ],
        "links": bundle["span_links"],
    }


class DatasetChecker:
    def __init__(self, *, seed=42, config=None):
        self.counts = Counter()
        self.hash = hashlib.sha256(
            encoded(
                {
                    "generator_version": GENERATOR_VERSION,
                    "seed": seed,
                    "config": config or {},
                }
            )
        )
        self.regions, self.tools, self.agent_counts = Counter(), Counter(), Counter()
        self.agent_keys = {}

    def consume(self, bundle):
        self.agent_keys.update(
            {agent["agent_id"]: index for index, agent in enumerate(bundle["agents"])}
        )
        spans = bundle["spans"]
        if (
            len(spans) != 500
            or sum(span["parent_span_id"] is None for span in spans) != 1
        ):
            raise ToolError("Expected a 500-Span single-root clone")
        by_id = {span["span_id"]: span for span in spans}
        if len(by_id) != len(spans):
            raise ToolError("Duplicate Span ID")
        for span in spans:
            parent = span["parent_span_id"]
            if parent and parent not in by_id:
                raise ToolError("Orphan Span")
            visited, current = set(), span
            while current["parent_span_id"]:
                if current["span_id"] in visited:
                    raise ToolError("Cyclic containment")
                visited.add(current["span_id"])
                current = by_id[current["parent_span_id"]]
            if span["operation_type"] != "LLM" and (
                span["input_tokens"] is not None or span["output_tokens"] is not None
            ):
                raise ToolError("Non-LLM Token value")
            if timestamp(span["start_time"]) > timestamp(span["end_time"]):
                raise ToolError("Invalid Span time")
            if len(encoded(span["attributes"])) != span["attributes"]["payload_size"]:
                raise ToolError("JSON payload size differs from manifest")
            self.regions[span["attributes"]["region"]] += 1
            self.tools[span["attributes"]["tool_category"]] += 1
            self.agent_counts[span["agent_id"]] += 1
            self.counts["errors"] += span["status"] == "ERROR"
        event_ids = [event["event_id"] for event in bundle["span_events"]]
        if len(set(event_ids)) != len(event_ids) or any(
            event["span_id"] not in by_id for event in bundle["span_events"]
        ):
            raise ToolError("Invalid event identity/reference")
        for key in ("agents", "tasks", "runs", "spans", "span_events", "span_links"):
            self.counts[key] += len(bundle[key])
        self.hash.update(encoded(logical_bundle(bundle, self.agent_keys)) + b"\n")

    def summary(self):
        return {
            "actual_counts": dict(self.counts),
            "content_hash": self.hash.hexdigest(),
            "distributions": {
                "region": dict(self.regions),
                "tool_category": dict(self.tools),
                "agent": {str(key): item for key, item in self.agent_counts.items()},
            },
            "generator_version": GENERATOR_VERSION,
        }
