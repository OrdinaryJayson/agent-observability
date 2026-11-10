"""In-memory recorder only. Run/trace IDs come from the run service."""

from contextlib import contextmanager
from datetime import datetime, timezone
import secrets
from uuid import uuid4

from app.recorder.contracts import EventData, SimulationResult, SpanData


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TraceRecorder:
    def __init__(self, *, run_id: str, trace_id: str):
        self.run_id, self.trace_id = run_id, trace_id
        self.spans: list[dict] = []
        self.events: list[dict] = []
        self._stack: list[dict] = []

    @contextmanager
    def span(self, name: str, operation_type: str, **fields):
        item = {
            "span_id": secrets.token_hex(8),
            "parent_span_id": self._stack[-1]["span_id"] if self._stack else None,
            "agent_id": None,
            "operation_type": operation_type,
            "span_name": name,
            "status": "SUCCESS",
            "start_time": utcnow(),
            "end_time": None,
            "provider": None,
            "model_name": None,
            "tool_name": None,
            "input_tokens": None,
            "output_tokens": None,
            "error_type": None,
            "error_message": None,
            "attributes": {},
            **fields,
        }
        self._stack.append(item)
        try:
            yield item
        except Exception as exc:
            item.update(
                status="ERROR",
                error_type=type(exc).__name__,
                error_message="Operation failed",
            )
            self.event("operation.failed", severity="ERROR", message="Operation failed")
            raise
        finally:
            item["end_time"] = utcnow()
            self._stack.pop()
            self.spans.append(SpanData.model_validate(item).model_dump())

    def event(self, name: str, *, severity: str = "INFO", message: str | None = None):
        if not self._stack:
            raise ValueError("Events require an active span")
        item = EventData(
            event_id=uuid4(),
            span_id=self._stack[-1]["span_id"],
            event_name=name,
            severity=severity,
            message=message,
            occurred_at=utcnow(),
            attributes={},
        ).model_dump()
        item["event_id"] = str(item["event_id"])
        self.events.append(item)

    def result(
        self, *, final_status: str, error_summary: str | None
    ) -> SimulationResult:
        if self._stack:
            raise ValueError("Cannot finish with open spans")
        return SimulationResult(
            self.spans.copy(), self.events.copy(), final_status, error_summary
        )
