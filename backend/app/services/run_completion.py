from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.database import get_engine
from app.core.errors import AppError
from app.recorder.contracts import EventData, SpanData
from app.repositories import execution


def validate_result(spans: list[dict], events: list[dict]):
    if not 1 <= len(spans) <= 500 or len(events) > 2000:
        raise ValueError("Expected 1–500 spans and at most 2000 events")
    parsed = [SpanData.model_validate(s).model_dump() for s in spans]
    parsed_events = [EventData.model_validate(e).model_dump() for e in events]
    by_id = {s["span_id"]: s for s in parsed}
    if len(by_id) != len(parsed):
        raise ValueError("Duplicate span ID")
    if sum(s["parent_span_id"] is None for s in parsed) != 1:
        raise ValueError("Exactly one root is required")
    for span in parsed:
        visited = set()
        current = span
        while current["parent_span_id"] is not None:
            if current["span_id"] in visited:
                raise ValueError("Cyclic span tree")
            visited.add(current["span_id"])
            parent = by_id.get(current["parent_span_id"])
            if parent is None:
                raise ValueError("Missing parent")
            current = parent
    event_ids = set()
    for event in parsed_events:
        if event["span_id"] not in by_id or event["event_id"] in event_ids:
            raise ValueError("Invalid event reference or duplicate ID")
        event_ids.add(event["event_id"])
    return parsed, parsed_events


def complete_run(
    *,
    run_id: str,
    spans: list[dict],
    events: list[dict],
    final_status: str,
    error_summary: str | None,
) -> None:
    if final_status not in {"SUCCESS", "FAILED"}:
        raise AppError(422, "VALIDATION_ERROR", "Unsupported final status")
    try:
        with get_engine().begin() as conn:
            run = execution.get_run(conn, run_id=run_id, lock=True)
            if run["status"] != "RUNNING":
                raise AppError(409, "CONFLICT", "Run has already finished")
            parsed, parsed_events = validate_result(spans, events)
            execution.save_result(
                conn, run_id, parsed, parsed_events, final_status, error_summary
            )
    except (ValueError, ValidationError) as exc:
        raise AppError(422, "VALIDATION_ERROR", "Invalid trace data") from exc
    except IntegrityError as exc:
        raise AppError(409, "CONFLICT", "Trace violates database constraints") from exc
