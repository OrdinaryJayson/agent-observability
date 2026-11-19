"""Pure ordered journal reduction and deterministic infrastructure-failure sealing."""

from collections import deque
from copy import deepcopy
from uuid import NAMESPACE_URL, UUID, uuid5

from .protocol import check_shape, iso, schema, timestamp

SYSTEM_KINDS = {
    "run.queued",
    "run.started",
    "run.recovering",
    "run.finished",
    "cancel.requested",
}


def _closed(spans, events, links, nodes, final_status, error_summary, *, journal_seq=0):
    result_spans = []
    for span in spans:
        if span["state"] == "RUNNING":
            raise ValueError("Projection contains an open span")
        fields = {
            key: item
            for key, item in span.items()
            if key not in {"node_key", "role_key", "attempt_no", "state"}
        }
        fields["attributes"] = deepcopy(span["attributes"]) | {
            "node_key": span["node_key"],
            "role_key": span["role_key"],
            "attempt_no": span["attempt_no"],
        }
        fields["status"] = span["state"]
        fields["start_time"], fields["end_time"] = (
            timestamp(fields["start_time"]),
            timestamp(fields["end_time"]),
        )
        fields["agent_id"] = (
            UUID(str(fields["agent_id"])) if fields["agent_id"] is not None else None
        )
        result_spans.append(fields)
    roots = [span for span in result_spans if span["parent_span_id"] is None]
    if result_spans and len(roots) != 1:
        raise ValueError("Projection must have exactly one root")
    by_id = {span["span_id"]: span for span in result_spans}
    if roots and (
        roots[0]["operation_type"] != "WORKFLOW" or roots[0]["agent_id"] is not None
    ):
        raise ValueError("Root must be an unbound WORKFLOW")
    for span in result_spans:
        seen = set()
        current = span
        while current["parent_span_id"] is not None:
            if current["span_id"] in seen or current["parent_span_id"] not in by_id:
                raise ValueError("Cyclic or orphan containment tree")
            seen.add(current["span_id"])
            current = by_id[current["parent_span_id"]]
    adjacency = {key: [] for key in by_id}
    degree = {key: 0 for key in by_id}
    for link in links:
        source, target = link["source_span_id"], link["target_span_id"]
        if source not in by_id or target not in by_id or source == target:
            raise ValueError("Invalid link endpoint")
        if link["link_type"] == "DEPENDS_ON":
            adjacency[source].append(target)
            degree[target] += 1
    ready = deque(key for key in degree if not degree[key])
    visited = 0
    while ready:
        key = ready.popleft()
        visited += 1
        for target in adjacency[key]:
            degree[target] -= 1
            if not degree[target]:
                ready.append(target)
    if visited != len(by_id):
        raise ValueError("Dependency links contain a cycle")
    root = roots[0] if roots else None
    logical = None
    for event in events:
        if event["event_name"] == "run.logical_completed":
            logical = event["attributes"]["logical_duration_ms"]
    mode = root["attributes"].get("time_basis", "REALTIME") if root else "REALTIME"
    if logical is None and root:
        logical = (root["end_time"] - root["start_time"]).total_seconds() * 1000
    if root:
        root["attributes"]["journal_seq"] = journal_seq
    return {
        "spans": result_spans,
        "events": deepcopy(events),
        "links": deepcopy(links),
        "nodes": deepcopy(nodes),
        "final_status": final_status,
        "error_summary": error_summary,
        "time_basis": mode,
        "logical_duration_ms": logical or 0,
    }


def reduce_journal(*, events: list[dict]) -> dict:
    spans, recorded_events, links, nodes = {}, {}, [], {}
    event_ids, sequences = set(), {}
    last_seq, run_id, terminal = 0, None, None
    recovery_intervals = []
    previous_recorded = None
    batch_schema = schema("journal-batch.schema.json")
    producer_rules = {
        rule["properties"]["kind"]["const"]: rule["properties"]["payload"]
        for rule in batch_schema["properties"]["events"]["items"]["oneOf"]
    }
    for event in events:
        seq = event["seq"]
        if seq in sequences:
            if sequences[seq] != event:
                raise ValueError("Conflicting duplicate sequence")
            continue
        if terminal is not None or seq != last_seq + 1:
            raise ValueError("Journal must be contiguous and terminate once")
        if run_id is not None and event["run_id"] != run_id:
            raise ValueError("Mixed Run IDs")
        run_id = event["run_id"]
        if event["producer_event_id"] in event_ids:
            raise ValueError("Duplicate producer event identity")
        event_ids.add(event["producer_event_id"])
        sequences[seq], last_seq = event, seq
        timestamp(event["occurred_at"])
        payload, kind = event["payload"], event["kind"]
        if kind in producer_rules:
            check_shape(payload, producer_rules[kind], root=batch_schema)
        if kind == "span.started":
            span_id = payload["span_id"]
            if span_id in spans or (
                payload["parent_span_id"] is not None
                and payload["parent_span_id"] not in spans
            ):
                raise ValueError("Duplicate span or missing parent")
            if (
                payload["parent_span_id"] is not None
                and spans[payload["parent_span_id"]]["state"] != "RUNNING"
            ):
                raise ValueError("Cannot attach to a closed parent")
            spans[span_id] = deepcopy(payload) | {
                "state": "RUNNING",
                "end_time": None,
                "input_tokens": None,
                "output_tokens": None,
                "provider": None,
                "model_name": None,
                "tool_name": None,
                "error_type": None,
                "error_message": None,
            }
            key = payload["node_key"]
            if key is not None:
                node = nodes.setdefault(
                    key,
                    {
                        "node_key": key,
                        "state": "PENDING",
                        "attempt_no": 0,
                        "span_ids": [],
                    },
                )
                if (
                    payload["attempt_no"] != node["attempt_no"] + 1
                    or node["state"] == "SUCCESS"
                ):
                    raise ValueError("Invalid or repeated logical attempt")
                node.update(state="RUNNING", attempt_no=payload["attempt_no"])
                node["span_ids"].append(span_id)
        elif kind == "span.finished":
            span = spans[payload["span_id"]]
            if span["state"] != "RUNNING" or any(
                item["parent_span_id"] == span["span_id"] and item["state"] == "RUNNING"
                for item in spans.values()
            ):
                raise ValueError("Span closed twice or before its children")
            if timestamp(payload["end_time"]) < timestamp(span["start_time"]):
                raise ValueError("Span ends before start")
            if span["operation_type"] != "LLM" and (
                payload["input_tokens"] is not None
                or payload["output_tokens"] is not None
            ):
                raise ValueError("Only LLM spans may carry tokens")
            span.update(deepcopy(payload), state=payload["status"])
            if span["node_key"] is not None:
                nodes[span["node_key"]]["state"] = (
                    "CANCELLED"
                    if payload["error_type"] == "RunCancelled"
                    else payload["status"]
                )
        elif kind == "span.event":
            parsed = deepcopy(payload)
            parsed["event_id"] = UUID(parsed["event_id"])
            parsed["occurred_at"] = timestamp(parsed["occurred_at"])
            if parsed["event_id"] in recorded_events or parsed["span_id"] not in spans:
                raise ValueError("Duplicate event or unknown span")
            recorded_events[parsed["event_id"]] = parsed
        elif kind == "link.created":
            if (
                any(
                    payload[key] not in spans
                    for key in ("source_span_id", "target_span_id")
                )
                or payload in links
            ):
                raise ValueError("Invalid link reference or duplicate")
            links.append(deepcopy(payload))
        elif kind == "node.skipped":
            key = payload["node_key"]
            if key in nodes and nodes[key]["state"] not in {"PENDING"}:
                raise ValueError("Cannot skip an already executed node")
            nodes[key] = {
                "node_key": key,
                "state": "CANCELLED"
                if payload["reason"] == "RunCancelled"
                else "SKIPPED",
                "attempt_no": 0,
                "span_ids": [],
            }
        elif kind == "run.finished":
            if payload["final_seq"] != seq:
                raise ValueError("Terminal watermark mismatch")
            terminal = payload
        elif kind not in SYSTEM_KINDS | {"checkpoint.saved"}:
            raise ValueError("Unknown journal event kind")
        if kind == "run.recovering" and previous_recorded:
            recovery_intervals.append([previous_recorded, event["recorded_at"]])
        previous_recorded = event.get("recorded_at", event["occurred_at"])
    if len(spans) > 500 or len(recorded_events) > 2000 or last_seq > 5000:
        raise ValueError("Projection exceeds execution limits")
    closed_result = None
    if terminal is not None and terminal["projection_complete"]:
        closed_result = _closed(
            list(spans.values()),
            list(recorded_events.values()),
            links,
            list(nodes.values()),
            terminal["status"],
            terminal["error_summary"],
            journal_seq=last_seq,
        )
        for span in closed_result["spans"]:
            if span["parent_span_id"] is None:
                span["attributes"]["recovery_intervals"] = recovery_intervals
    return {
        "nodes": list(nodes.values()),
        "spans": list(spans.values()),
        "events": list(recorded_events.values()),
        "links": links,
        "closed_result": closed_result,
    }


def seal_interrupted(*, events: list[dict], reason: str, ended_at) -> dict:
    projection = reduce_journal(events=events)
    if projection["closed_result"] is not None:
        return projection["closed_result"]
    spans, span_events, nodes = (
        deepcopy(projection["spans"]),
        deepcopy(projection["events"]),
        deepcopy(projection["nodes"]),
    )
    watermark = max((event["seq"] for event in events), default=0)
    run_id = events[0]["run_id"] if events else "unstarted"
    for span in spans:
        if span["state"] != "RUNNING":
            continue
        if timestamp(ended_at) < timestamp(span["start_time"]):
            raise ValueError("Sealing time precedes a recorded span")
        span.update(
            state="ERROR",
            status="ERROR",
            end_time=iso(ended_at),
            error_type="WorkerLost",
            error_message=reason,
        )
        if len(span_events) < 2000:
            span_events.append(
                dict(
                    event_id=uuid5(
                        NAMESPACE_URL,
                        f"{run_id}:{watermark}:{reason}:{span['span_id']}",
                    ),
                    span_id=span["span_id"],
                    event_name="worker.lost",
                    severity="ERROR",
                    message=reason,
                    occurred_at=timestamp(ended_at),
                    attributes={"source_seq": watermark},
                )
            )
    for node in nodes:
        if node["state"] == "RUNNING":
            node["state"] = "ERROR"
    return _closed(
        spans,
        span_events,
        projection["links"],
        nodes,
        "FAILED",
        reason,
        journal_seq=watermark,
    )
