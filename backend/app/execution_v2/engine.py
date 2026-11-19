"""Deterministic bounded-concurrency scheduler over injectable async clocks/Sinks.

The scheduler keeps logical operations in flight concurrently. Simulated work has
no external side effects. One owner serializes recorder/checkpoint mutations.
"""

from copy import deepcopy
import hashlib
import random
from datetime import timedelta
from uuid import uuid4

from .protocol import (
    EngineError,
    check_shape,
    encoded,
    iso,
    mapping,
    schema,
    timestamp,
    value,
)
from .recorder import IncrementalRecorder
from .validation import OPERATIONS, graph, validate_workflow


def node_random(seed: int, node_key: str, attempt_no: int) -> random.Random:
    material = f"{seed}:{node_key}:{attempt_no}".encode()
    return random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))


class _Execution:
    def __init__(self, context, sink):
        self.context, self.sink = context, sink
        self.definition = value(context, "definition")
        report = validate_workflow(self.definition)
        if not report["valid"]:
            raise EngineError(
                "WORKFLOW_INVALID", "Invalid workflow", errors=report["errors"]
            )
        self.nodes, self.incoming, self.outgoing = graph(self.definition)
        self.config = mapping(value(context, "config", {}))
        self.clock = value(context, "clock")
        self.epoch = value(context, "lease_epoch")
        self.last_seq = value(context, "last_seq")
        self.definition_hash = value(context, "definition_hash")
        self.parallelism = self.config.get("max_parallelism", 4)
        self.seed = self.config.get("seed", 42)
        if type(self.parallelism) is not int or not 1 <= self.parallelism <= 4:
            raise EngineError("WORKFLOW_INVALID", "Parallelism must be 1–4")
        if type(self.seed) is not int or not -2147483648 <= self.seed <= 2147483647:
            raise EngineError("WORKFLOW_INVALID", "Seed must be int32")
        if self.clock.mode != self.config.get("mode", "REALTIME"):
            raise EngineError("CHECKPOINT_CONFLICT", "Clock mode does not match config")
        self.bindings = {
            key: str(item) for key, item in value(context, "agent_bindings", {}).items()
        }
        roles = {role["role_key"] for role in self.definition["roles"]}
        if set(self.bindings) - roles or (
            not self.config.get("unbound", False) and set(self.bindings) != roles
        ):
            raise EngineError(
                "WORKFLOW_INVALID", "Role bindings do not match the workflow"
            )
        self.states = {
            key: {"state": "PENDING", "attempt_no": 0, "result": None, "span_ids": []}
            for key in self.nodes
        }
        self.attempts, self.routes = [], {}
        self.recorder = IncrementalRecorder(self.clock)
        self.inflight, self.ready_times = {}, {}
        self.cancelled = False
        self.error = None
        self.roles = {}
        self.root = None
        self.checkpoint = deepcopy(value(context, "checkpoint") or {})

    async def control(self) -> None:
        control = mapping(await self.sink.control())
        if not control["lease_valid"]:
            raise EngineError("LEASE_LOST", "Lease is no longer valid")
        self.cancelled |= control["cancel_requested"]
        if self.clock.mode == "REALTIME" and self.clock.now() >= timestamp(
            control["deadline_at"]
        ):
            self.error = "DeadlineExceeded"
        if self.clock.elapsed_ms > 60000:
            self.error = "BudgetExceeded"

    def checkpoint_value(self) -> dict:
        return {
            "checkpoint_version": 1,
            "definition_hash": self.definition_hash,
            "clock_mode": self.clock.mode,
            "logical_time_ms": self.clock.elapsed_ms,
            "node_states": deepcopy(self.states),
            "attempts": deepcopy(self.attempts),
            "open_spans": deepcopy(list(self.recorder.open_spans.values())),
            "completed_span_ids": self.recorder.completed.copy(),
            "resolved_routes": self.routes.copy(),
            "journal_seq": self.last_seq,
        }

    async def flush(self, terminal=None) -> None:
        await self.control()
        if not self.recorder.events and terminal is None:
            self.recorder.emit("checkpoint.saved", {"checkpoint_version": 1})
        batch = {
            "protocol_version": "2.0",
            "run_id": str(value(self.context, "run_id")),
            "batch_id": str(uuid4()),
            "lease_epoch": self.epoch,
            "expected_last_seq": self.last_seq,
            "events": deepcopy(self.recorder.events),
            "checkpoint": self.checkpoint_value(),
            "terminal": terminal,
        }
        if self.last_seq + len(batch["events"]) + 1 > 5000:
            raise EngineError("BUDGET_EXCEEDED", "Journal limit exceeded")
        check_shape(batch, schema("journal-batch.schema.json"))
        if (
            len(encoded(batch)) > 512 * 1024
            or len(encoded(batch["checkpoint"])) > 256 * 1024
        ):
            raise EngineError(
                "BUDGET_EXCEEDED", "Serialized batch/checkpoint limit exceeded"
            )
        for attempt in range(3):
            try:
                ack = mapping(await self.sink.commit(deepcopy(batch)))
                break
            except (OSError, ConnectionError):
                if attempt == 2:
                    raise
                # A transport failure has an unknown outcome. Resend identical IDs
                # and payload. The Sink owns fencing and receipt lookup.
        if (
            ack["batch_id"] != batch["batch_id"]
            or str(ack["run_id"]) != batch["run_id"]
        ):
            raise EngineError("CHECKPOINT_CONFLICT", "ACK identity mismatch")
        if ack["last_seq"] < self.last_seq + len(batch["events"]):
            raise EngineError("CHECKPOINT_CONFLICT", "ACK watermark moved backwards")
        if terminal is not None and not ack["terminal_committed"]:
            raise EngineError("CHECKPOINT_CONFLICT", "Terminal ACK is incomplete")
        self.last_seq = ack["last_seq"]
        self.recorder.events.clear()
        self._last_checkpoint_ms = self.clock.elapsed_ms

    def begin(self) -> None:
        self.root = self.recorder.start(
            "Task Execution",
            "WORKFLOW",
            attributes={
                "time_basis": self.clock.mode,
                "definition_hash": self.definition_hash,
                "logical_start_ms": self.clock.elapsed_ms,
            },
        )
        for role in self.definition["roles"]:
            self.roles[role["role_key"]] = self.recorder.start(
                role["name"],
                "AGENT",
                parent_span_id=self.root,
                role_key=role["role_key"],
                agent_id=self.bindings.get(role["role_key"]),
            )

    async def restore(self) -> None:
        cp = self.checkpoint
        check_shape(
            cp,
            schema("journal-batch.schema.json")["$defs"]["checkpoint"],
            root=schema("journal-batch.schema.json"),
        )
        if (
            cp["definition_hash"] != self.definition_hash
            or cp["clock_mode"] != self.clock.mode
            or cp["journal_seq"] != self.last_seq
            or set(cp["node_states"]) != set(self.nodes)
        ):
            raise EngineError(
                "CHECKPOINT_CONFLICT",
                "Checkpoint definition, mode or watermark mismatch",
            )
        if self.epoch > 3:
            raise EngineError("BUDGET_EXCEEDED", "Worker recovery limit exceeded")
        known = cp["completed_span_ids"] + [
            span["span_id"] for span in cp["open_spans"]
        ]
        if len(set(known)) != len(known) or len(known) > 500:
            raise EngineError(
                "CHECKPOINT_CONFLICT", "Checkpoint span identities overlap"
            )
        by_attempt = {item["span_id"]: item for item in cp["attempts"]}
        if len(by_attempt) != len(cp["attempts"]):
            raise EngineError("CHECKPOINT_CONFLICT", "Duplicate checkpoint attempt")
        for key, state in cp["node_states"].items():
            attempts = [by_attempt.get(span_id) for span_id in state["span_ids"]]
            if any(item is None or item["node_key"] != key for item in attempts):
                raise EngineError(
                    "CHECKPOINT_CONFLICT", "Checkpoint node/attempt identity mismatch"
                )
            if [item["attempt_no"] for item in attempts] != list(
                range(1, state["attempt_no"] + 1)
            ):
                raise EngineError(
                    "CHECKPOINT_CONFLICT", "Checkpoint attempt sequence mismatch"
                )
        for span in cp["open_spans"]:
            if span["operation_type"] == "AGENT" and span[
                "agent_id"
            ] != self.bindings.get(span["role_key"]):
                raise EngineError("CHECKPOINT_CONFLICT", "Recovery binding changed")
        original_root = next(
            (span for span in cp["open_spans"] if span["parent_span_id"] is None), None
        )
        if self.clock.mode == "VIRTUAL" and original_root is not None:
            origin = timestamp(original_root["start_time"]) - timedelta(
                milliseconds=original_root["attributes"].get("logical_start_ms", 0)
            )
            self.clock.restore(cp["logical_time_ms"], origin=origin)
        else:
            self.clock.restore(cp["logical_time_ms"])
        self.states, self.attempts, self.routes = (
            deepcopy(cp["node_states"]),
            deepcopy(cp["attempts"]),
            cp["resolved_routes"].copy(),
        )
        self.recorder = IncrementalRecorder(
            self.clock,
            open_spans=cp["open_spans"],
            completed_span_ids=cp["completed_span_ids"],
            event_count=2 * len(cp["attempts"]),
        )
        roots = [
            span
            for span in self.recorder.open_spans.values()
            if span["parent_span_id"] is None
        ]
        if len(roots) != 1:
            raise EngineError("CHECKPOINT_CONFLICT", "Recovery requires one open root")
        self.root = roots[0]["span_id"]
        self.roles = {
            span["role_key"]: span["span_id"]
            for span in cp["open_spans"]
            if span["operation_type"] == "AGENT"
        }
        interrupted = [
            span for span in cp["open_spans"] if span["node_key"] is not None
        ]
        for span in interrupted:
            key = span["node_key"]
            self.recorder.finish(
                span["span_id"],
                status="ERROR",
                error_type="WorkerLost",
                error_message="Worker lease was interrupted",
            )
            next(item for item in self.attempts if item["span_id"] == span["span_id"])[
                "state"
            ] = "ERROR"
            self.states[key]["state"] = "PENDING"
            self.ready_times[key] = iso(self.clock.now())
            self.start_node(
                key,
                business_attempt=span["attributes"].get("business_attempt_no", 1),
                recovery=True,
            )
        self.recorder.event(
            self.root, "worker.recovered", attributes={"lease_epoch": self.epoch}
        )
        if any(state["state"] == "ERROR" for state in self.states.values()):
            self.error = "NodeFailed"

    def start_node(
        self, key: str, *, business_attempt=1, retry_delay_ms=0, recovery=False
    ) -> None:
        node, state = self.nodes[key], self.states[key]
        attempt_no = state["attempt_no"] + 1
        rng = node_random(self.seed, key, attempt_no)
        result = None
        if node["type"] == "CONDITION":
            selected = node["config"]["result"]
            result = rng.choice(["PASS", "FAIL"]) if selected == "SEEDED" else selected
            self.routes[key] = result
        now = iso(self.clock.now())
        parent = self.roles.get(node["role_key"], self.root)
        span_id = self.recorder.start(
            node["name"],
            node["type"] if node["type"] in OPERATIONS else "WORKFLOW",
            parent_span_id=parent,
            node_key=key,
            role_key=node["role_key"],
            attempt_no=attempt_no,
            agent_id=self.bindings.get(node["role_key"]),
            attributes={
                "node_key": key,
                "role_key": node["role_key"],
                "attempt_no": attempt_no,
                "ready_at": self.ready_times.get(key, now),
                "retry_delay_ms": retry_delay_ms,
                "business_attempt_no": business_attempt,
                "recovery_attempt": recovery,
                "result": result,
                "logical_start_ms": self.clock.elapsed_ms,
            },
        )
        if state["span_ids"]:
            self.recorder.emit(
                "link.created",
                {
                    "source_span_id": state["span_ids"][-1],
                    "target_span_id": span_id,
                    "link_type": "RETRY_OF",
                },
            )
        for edge in self.incoming[key]:
            previous = self.states[edge["source"]]
            if (
                previous["state"] == "SUCCESS"
                and self.edge_active(edge)
                and previous["span_ids"]
            ):
                self.recorder.emit(
                    "link.created",
                    {
                        "source_span_id": previous["span_ids"][-1],
                        "target_span_id": span_id,
                        "link_type": "DEPENDS_ON",
                    },
                )
        state.update(state="RUNNING", attempt_no=attempt_no, result=result)
        state["span_ids"].append(span_id)
        attempt = {
            "node_key": key,
            "attempt_no": attempt_no,
            "span_id": span_id,
            "state": "RUNNING",
        }
        self.attempts.append(attempt)
        self.recorder.event(span_id, "node.started")
        self.inflight[key] = {
            "span_id": span_id,
            "due": self.clock.elapsed_ms + node["config"].get("duration_ms", 0),
            "failed": rng.random() < node["config"].get("failure_probability", 0),
            "business_attempt": business_attempt,
            "attempt": attempt,
        }

    def edge_active(self, edge: dict) -> bool:
        return (
            edge["route"] == "ALWAYS"
            or self.routes.get(edge["source"]) == edge["route"]
        )

    def readiness(self, key: str) -> str:
        edges = self.incoming[key]
        if any(
            self.states[edge["source"]]["state"] in {"PENDING", "RUNNING"}
            for edge in edges
        ):
            return "WAIT"
        active = [
            edge
            for edge in edges
            if self.edge_active(edge)
            and self.states[edge["source"]]["state"] != "SKIPPED"
        ]
        if not edges:
            return "READY"
        if not active or any(
            self.states[edge["source"]]["state"] != "SUCCESS" for edge in active
        ):
            return "SKIP"
        return "READY"

    def skip(self, key: str, reason: str) -> None:
        self.states[key]["state"] = (
            "CANCELLED" if reason == "RunCancelled" else "SKIPPED"
        )
        self.recorder.emit("node.skipped", {"node_key": key, "reason": reason})

    async def wait(self, duration_ms: float) -> None:
        remaining = duration_ms
        while remaining > 0:
            await self.control()
            if self.cancelled or self.error in {"DeadlineExceeded", "BudgetExceeded"}:
                return
            step = min(100, remaining)
            await self.clock.wait_ms(step)
            remaining -= step

    async def complete_node(self, key: str) -> None:
        item = self.inflight[key]
        node = self.nodes[key]
        config = node["config"]
        failed = item["failed"]
        backoff = item.get("phase") == "BACKOFF"
        if (
            failed
            and not backoff
            and not self.error
            and item["business_attempt"] <= config.get("max_retries", 0)
        ):
            item.update(
                phase="BACKOFF",
                failed_at=self.clock.now(),
                retry_delay_ms=100 * item["business_attempt"],
            )
            item["due"] = self.clock.elapsed_ms + item["retry_delay_ms"]
            # Keep this attempt open in durable checkpoints until the failed
            # close and retry open can be committed atomically. Other branches
            # continue to complete during the bounded backoff interval.
            return
        self.inflight.pop(key)
        finished_at = item.get("failed_at", self.clock.now())
        self.recorder.event(
            item["span_id"],
            "node.failed" if failed else "node.completed",
            severity="ERROR" if failed else "INFO",
            occurred_at=finished_at,
        )
        self.recorder.finish(
            item["span_id"],
            status="ERROR" if failed else "SUCCESS",
            input_tokens=config.get("input_tokens", 50)
            if node["type"] == "LLM"
            else None,
            output_tokens=config.get("output_tokens", 20)
            if node["type"] == "LLM"
            else None,
            error_type="SimulatedNodeError" if failed else None,
            error_message="Simulated operation failed" if failed else None,
            ended_at=finished_at,
        )
        item["attempt"]["state"] = "ERROR" if failed else "SUCCESS"
        self.states[key]["state"] = "ERROR" if failed else "SUCCESS"
        if backoff:
            if not self.cancelled and not self.error:
                self.ready_times[key] = iso(self.clock.now())
                self.start_node(
                    key,
                    business_attempt=item["business_attempt"] + 1,
                    retry_delay_ms=item["retry_delay_ms"],
                )
                return
        if failed:
            self.error = self.error or "NodeFailed"

    async def run(self) -> None:
        await self.control()
        if self.checkpoint:
            await self.restore()
        else:
            self.begin()
        await self.flush()
        while True:
            await self.control()
            if self.cancelled or self.error:
                for key, state in self.states.items():
                    if state["state"] == "PENDING":
                        self.skip(key, "RunCancelled" if self.cancelled else self.error)
            else:
                for key in sorted(self.nodes):
                    if self.states[key]["state"] != "PENDING":
                        continue
                    ready = self.readiness(key)
                    if ready == "SKIP":
                        self.skip(key, "InactiveBranch")
                    elif ready == "READY":
                        self.ready_times.setdefault(key, iso(self.clock.now()))
                        if len(self.inflight) < self.parallelism:
                            self.start_node(key)
            if self.cancelled or self.error in {"DeadlineExceeded", "BudgetExceeded"}:
                for key, item in list(self.inflight.items()):
                    if item.get("phase") == "BACKOFF":
                        await self.complete_node(key)
                        continue
                    self.recorder.finish(
                        item["span_id"],
                        status="ERROR",
                        error_type="RunCancelled" if self.cancelled else self.error,
                        error_message="Execution stopped",
                    )
                    item["attempt"]["state"] = "ERROR"
                    self.states[key]["state"] = (
                        "CANCELLED" if self.cancelled else "ERROR"
                    )
                    del self.inflight[key]
            due = sorted(
                key
                for key, item in self.inflight.items()
                if item["due"] <= self.clock.elapsed_ms
            )
            for key in due:
                await self.complete_node(key)
                await self.flush()
            if self.recorder.events:
                await self.flush()
            if all(
                state["state"] not in {"PENDING", "RUNNING"}
                for state in self.states.values()
            ):
                break
            if due:
                continue
            if self.inflight:
                delay = min(
                    100,
                    max(
                        0,
                        min(item["due"] for item in self.inflight.values())
                        - self.clock.elapsed_ms,
                    ),
                )
                await self.wait(delay)
            else:
                # A skipped branch may make its merge decidable on the next pass.
                if not any(
                    self.readiness(key) != "WAIT"
                    for key, state in self.states.items()
                    if state["state"] == "PENDING"
                ):
                    raise EngineError(
                        "WORKFLOW_INVALID", "Scheduler cannot make progress"
                    )
            if self.clock.elapsed_ms - getattr(self, "_last_checkpoint_ms", 0) >= 200:
                await self.flush()
                self._last_checkpoint_ms = self.clock.elapsed_ms
            if self.last_seq >= 4936:
                self.error = "BudgetExceeded"
        final = (
            "CANCELLED" if self.cancelled else ("FAILED" if self.error else "SUCCESS")
        )
        for role, span_id in self.roles.items():
            failed = any(
                self.nodes[key]["role_key"] == role
                and state["state"] in {"ERROR", "CANCELLED"}
                for key, state in self.states.items()
            )
            self.recorder.finish(
                span_id,
                status="ERROR" if failed else "SUCCESS",
                error_type=self.error or "RunCancelled" if failed else None,
            )
        self.recorder.event(
            self.root,
            "run.logical_completed",
            attributes={
                "logical_duration_ms": self.clock.elapsed_ms,
                "time_basis": self.clock.mode,
            },
        )
        self.recorder.finish(
            self.root,
            status="SUCCESS" if final == "SUCCESS" else "ERROR",
            error_type="RunCancelled" if self.cancelled else self.error,
        )
        await self.flush(
            {
                "status": final,
                "error_summary": None
                if final == "SUCCESS"
                else ("RunCancelled" if self.cancelled else self.error),
            }
        )


async def execute_workflow(*, context, sink) -> None:
    await _Execution(context, sink).run()
