"""Incremental recorder. Parent context is isolated per asyncio task and instance."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import secrets
from uuid import uuid4

from .protocol import EngineError, iso


class IncrementalRecorder:
    def __init__(self, clock, *, open_spans=(), completed_span_ids=(), event_count=0):
        self.clock = clock
        self.open_spans = {span["span_id"]: deepcopy(span) for span in open_spans}
        self.completed = list(completed_span_ids)
        self.events = []
        self.event_count = event_count
        self.parent = ContextVar(f"recorder_parent_{id(self)}", default=None)

    @contextmanager
    def under(self, span_id: str):
        token = self.parent.set(span_id)
        try:
            yield
        finally:
            self.parent.reset(token)

    def emit(self, kind: str, payload: dict) -> None:
        self.events.append(
            {
                "producer_event_id": str(uuid4()),
                "kind": kind,
                "payload": deepcopy(payload),
                "occurred_at": iso(self.clock.now()),
            }
        )

    def start(
        self,
        name: str,
        operation_type: str,
        *,
        parent_span_id=None,
        agent_id=None,
        node_key=None,
        role_key=None,
        attempt_no=1,
        attributes=None,
    ) -> str:
        if len(self.open_spans) + len(self.completed) >= 500:
            raise EngineError("BUDGET_EXCEEDED", "Span budget exhausted")
        parent_span_id = parent_span_id or self.parent.get()
        if parent_span_id is not None and parent_span_id not in self.open_spans:
            raise ValueError("Parent must be open")
        if parent_span_id is None and (self.open_spans or self.completed):
            raise ValueError("Exactly one root is allowed")
        span_id = secrets.token_hex(8)
        while span_id in self.open_spans or span_id in self.completed:
            span_id = secrets.token_hex(8)
        span = {
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "agent_id": agent_id,
            "operation_type": operation_type,
            "span_name": name,
            "node_key": node_key,
            "role_key": role_key,
            "attempt_no": attempt_no,
            "start_time": iso(self.clock.now()),
            "attributes": attributes or {},
        }
        self.open_spans[span_id] = span
        self.emit("span.started", span)
        return span_id

    def finish(
        self,
        span_id: str,
        *,
        status="SUCCESS",
        input_tokens=None,
        output_tokens=None,
        error_type=None,
        error_message=None,
        ended_at=None,
    ) -> None:
        span = self.open_spans[span_id]
        if any(item["parent_span_id"] == span_id for item in self.open_spans.values()):
            raise ValueError("Children must close before their parent")
        llm = span["operation_type"] == "LLM"
        if not llm and (input_tokens is not None or output_tokens is not None):
            raise ValueError("Only LLM attempts carry tokens")
        payload = {
            "span_id": span_id,
            "status": status,
            "end_time": iso(ended_at or self.clock.now()),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "provider": "simulated" if llm else None,
            "model_name": "mock-v2" if llm else None,
            "tool_name": span["node_key"]
            if span["operation_type"] in {"TOOL", "RETRIEVAL"}
            else None,
            "error_type": error_type,
            "error_message": error_message,
        }
        self.emit("span.finished", payload)
        del self.open_spans[span_id]
        self.completed.append(span_id)

    def event(
        self,
        span_id: str,
        name: str,
        *,
        severity="INFO",
        attributes=None,
        occurred_at=None,
    ) -> None:
        if self.event_count >= 1984:
            raise EngineError("BUDGET_EXCEEDED", "Span Event closure reserve reached")
        self.emit(
            "span.event",
            {
                "event_id": str(uuid4()),
                "span_id": span_id,
                "event_name": name,
                "severity": severity,
                "message": name,
                "occurred_at": iso(occurred_at or self.clock.now()),
                "attributes": attributes or {},
            },
        )
        self.event_count += 1
