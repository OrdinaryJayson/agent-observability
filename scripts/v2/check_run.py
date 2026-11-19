"""Reconcile a terminal snapshot, full durable journal and v1 final projection."""

from datetime import datetime
from uuid import UUID

from _common import HttpClient, ToolError, parser, run_cli
from app.execution_v2 import reduce_journal
from app.execution_v2.protocol import iso


def _wire(record):
    if isinstance(record, dict):
        return {key: _wire(item) for key, item in record.items()}
    if isinstance(record, list):
        return [_wire(item) for item in record]
    if isinstance(record, datetime):
        return iso(record)
    if isinstance(record, UUID):
        return str(record)
    return record


def _legacy_items(client, path, maximum):
    output = []
    for page_number in range(1, maximum // 100 + 2):
        page = client.request(
            "GET", f"{path}?page={page_number}&page_size=100", raw=True
        )
        output.extend(page["data"])
        if len(output) == page["meta"]["total"]:
            return output
        if not page["data"] or len(output) > maximum:
            break
    raise ToolError("Legacy projection pagination is incomplete or exceeds its budget")


def check_run(client, run_id):
    snapshot = client.request("GET", f"/runs/{run_id}/snapshot")
    if snapshot["run"]["status"] == "RUNNING" or not snapshot["projection_complete"]:
        raise ToolError("Run does not have a complete terminal projection")
    events, cursor = [], 0
    while cursor < snapshot["seq"]:
        page = client.request(
            "GET", f"/runs/{run_id}/journal?after_seq={cursor}&limit=100", raw=True
        )
        batch = [event for event in page["data"] if event["seq"] <= snapshot["seq"]]
        if not batch or len(events) + len(batch) > 5000:
            raise ToolError("Journal is incomplete or exceeds its record budget")
        events.extend(batch)
        cursor = batch[-1]["seq"]
    projection = reduce_journal(events=events)
    closed = projection["closed_result"]
    if closed is None:
        raise ToolError("Journal does not replay to a complete terminal projection")
    replay_spans = {span["span_id"]: span for span in projection["spans"]}
    snapshot_spans = {span["span_id"]: span for span in snapshot["spans"]}
    replay_nodes = {item["node_key"]: item for item in projection["nodes"]}
    snapshot_nodes = {item["node_key"]: item for item in snapshot["nodes"]}
    replay_links = {tuple(sorted(item.items())) for item in projection["links"]}
    snapshot_links = {tuple(sorted(item.items())) for item in snapshot["links"]}
    if (
        replay_spans != snapshot_spans
        or replay_nodes != snapshot_nodes
        or replay_links != snapshot_links
    ):
        raise ToolError("Snapshot differs from its durable journal replay")
    if len(closed["events"]) != snapshot["event_count"]:
        raise ToolError("Snapshot Event count differs from replay")
    legacy = HttpClient(client.url.removesuffix("/api/v2") + "/api/v1")
    trace = legacy.request("GET", f"/traces/{snapshot['run']['trace_id']}")
    if trace["span_count"] != len(closed["spans"]) or trace["error_count"] != sum(
        span["status"] == "ERROR" for span in closed["spans"]
    ):
        raise ToolError("v1 persisted projection differs from v2 journal")
    path = f"/traces/{snapshot['run']['trace_id']}"
    stored_spans = _legacy_items(legacy, path + "/spans", 500)
    stored_events = _legacy_items(legacy, path + "/events", 2000)
    span_map = {
        span["span_id"]: {
            key: item for key, item in span.items() if key != "duration_ms"
        }
        for span in stored_spans
    }
    event_map = {event["event_id"]: event for event in stored_events}
    if len(span_map) != len(stored_spans) or span_map != {
        span["span_id"]: _wire(span) for span in closed["spans"]
    }:
        raise ToolError("Stored Span content or Token values differ from replay")
    if len(event_map) != len(stored_events) or event_map != {
        str(event["event_id"]): _wire(event) for event in closed["events"]
    }:
        raise ToolError("Stored Span Events differ from replay")
    return {
        "run_id": run_id,
        "journal_seq": snapshot["seq"],
        "span_count": len(closed["spans"]),
        "event_count": len(closed["events"]),
        "input_tokens": sum(
            span["input_tokens"] or 0
            for span in closed["spans"]
            if span["operation_type"] == "LLM"
        ),
        "output_tokens": sum(
            span["output_tokens"] or 0
            for span in closed["spans"]
            if span["operation_type"] == "LLM"
        ),
        "checks": {
            "contiguous_seq": True,
            "snapshot_equals_replay": True,
            "final_projection_counts": True,
            "final_projection_content": True,
        },
    }


def main(argv=None):
    cli = parser(__doc__)
    cli.add_argument("--run-id", type=UUID, required=True)
    args = cli.parse_args(argv)
    return run_cli(
        lambda args, summary: summary.update(
            check_run(HttpClient(args.base_url), str(args.run_id))
        ),
        args,
    )


if __name__ == "__main__":
    raise SystemExit(main())
