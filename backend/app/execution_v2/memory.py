"""Transactional in-memory reference Sink for independent protocol/fault tests.

This is a test adapter. PostgreSQL durability and cross-process fencing belong
to B's persistent Sink and require the separate integration suite.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .projection import reduce_journal
from .protocol import EngineError, check_shape, digest, iso, schema


def batch_semantics(batch: dict) -> str:
    content = deepcopy(batch)
    for key in ("expected_last_seq", "lease_epoch", "batch_id"):
        content.pop(key, None)
    content["checkpoint"].pop("journal_seq", None)
    return digest(content)


class MemorySink:
    def __init__(self, run_id: str, *, lease_epoch=1):
        self.run_id = str(run_id)
        self.lease_epoch = lease_epoch
        self.lease_valid = True
        self.cancel_requested = False
        self.deadline_at = datetime.now(timezone.utc) + timedelta(seconds=600)
        self.events, self.receipts = [], {}
        self.checkpoint = None
        self.terminal = None
        self.fail_before_commit = 0
        self.lose_ack = 0
        self.commit_calls = []
        self.system_event("run.queued", {"execution_state": "QUEUED"})
        self.system_event("run.started", {"lease_epoch": lease_epoch})

    @property
    def last_seq(self):
        return len(self.events)

    def system_event(self, kind, payload):
        now = iso(datetime.now(timezone.utc))
        self.events.append(
            {
                "run_id": self.run_id,
                "seq": self.last_seq + 1,
                "producer_event_id": str(uuid4()),
                "kind": kind,
                "payload": deepcopy(payload),
                "occurred_at": now,
                "recorded_at": now,
            }
        )

    async def control(self) -> dict:
        return {
            "lease_valid": self.lease_valid,
            "cancel_requested": self.cancel_requested,
            "deadline_at": iso(self.deadline_at),
            "last_seq": self.last_seq,
        }

    async def commit(self, batch: dict) -> dict:
        self.commit_calls.append(deepcopy(batch))
        check_shape(batch, schema("journal-batch.schema.json"))
        semantics = batch_semantics(batch)
        if batch["batch_id"] in self.receipts:
            old_hash, ack = self.receipts[batch["batch_id"]]
            if semantics != old_hash:
                raise EngineError(
                    "CHECKPOINT_CONFLICT", "Batch identity has different content"
                )
            return deepcopy(ack) | {"duplicate": True}
        if not self.lease_valid or batch["lease_epoch"] != self.lease_epoch:
            raise EngineError("LEASE_LOST", "Fenced producer")
        if self.terminal:
            raise EngineError("CHECKPOINT_CONFLICT", "Run is already terminal")
        if self.fail_before_commit:
            self.fail_before_commit -= 1
            raise ConnectionError("Injected failure before commit")
        previous = batch["expected_last_seq"]
        if previous != self.last_seq:
            additions = self.events[previous:]
            if previous > self.last_seq or any(
                event["kind"] not in {"cancel.requested", "run.recovering"}
                for event in additions
            ):
                raise EngineError(
                    "CHECKPOINT_CONFLICT",
                    "Producer watermark changed",
                    last_seq=self.last_seq,
                )
            # Safe system-only rebase is a Sink responsibility. Business payload
            # and IDs remain identical, as required by the frozen protocol.
        known = {event["producer_event_id"] for event in self.events}
        if batch["run_id"] != self.run_id or any(
            event["producer_event_id"] in known for event in batch["events"]
        ):
            raise EngineError(
                "CHECKPOINT_CONFLICT", "Foreign run or reused event identity"
            )
        first = self.last_seq + 1
        pending = deepcopy(self.events)
        now = iso(datetime.now(timezone.utc))
        for event in batch["events"]:
            pending.append(
                deepcopy(event)
                | {"run_id": self.run_id, "seq": len(pending) + 1, "recorded_at": now}
            )
        if batch["terminal"]:
            pending.append(
                {
                    "run_id": self.run_id,
                    "seq": len(pending) + 1,
                    "producer_event_id": str(uuid4()),
                    "kind": "run.finished",
                    "payload": batch["terminal"]
                    | {"projection_complete": True, "final_seq": len(pending) + 1},
                    "occurred_at": now,
                    "recorded_at": now,
                }
            )
        reduce_journal(events=pending)
        checkpoint = deepcopy(batch["checkpoint"])
        checkpoint["journal_seq"] = len(pending)
        ack = {
            "run_id": self.run_id,
            "batch_id": batch["batch_id"],
            "first_seq": first,
            "last_seq": len(pending),
            "duplicate": False,
            "terminal_committed": batch["terminal"] is not None,
        }
        self.events, self.checkpoint = pending, checkpoint
        self.terminal = deepcopy(batch["terminal"])
        self.receipts[batch["batch_id"]] = semantics, deepcopy(ack)
        if self.lose_ack:
            self.lose_ack -= 1
            raise ConnectionError("Injected failure after commit before ACK")
        return ack

    def recover(self):
        self.lease_epoch += 1
        self.lease_valid = True
        self.system_event("run.recovering", {"lease_epoch": self.lease_epoch})
        if self.checkpoint:
            self.checkpoint["journal_seq"] = self.last_seq

    def projection(self):
        return reduce_journal(events=self.events)
