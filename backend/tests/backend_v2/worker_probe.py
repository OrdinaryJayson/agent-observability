"""Subprocess harness using frozen C outputs; not a real DAG implementation.

It exercises the production Worker/Sink/database code without touching C's
directories. IDs are namespaced per run solely for fixture isolation.
"""

import asyncio
import copy
import json
import sys
import types
from pathlib import Path
from uuid import UUID, uuid5

SAMPLES = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts/v2/examples.json").read_text(
        encoding="utf-8"
    )
)


def projection(events):
    producers = [
        e
        for e in events
        if e["kind"].startswith(("span.", "link.", "node.", "checkpoint."))
    ]
    snapshot = (
        SAMPLES["running_snapshot"] if len(producers) <= 6 else SAMPLES["snapshot"]
    )
    final = copy.deepcopy(snapshot)
    closed = None
    collected = [e["payload"] for e in events if e["kind"] == "span.event"]
    if len(producers) > 6:
        spans = []
        for span in final["spans"]:
            value = {
                k: v
                for k, v in span.items()
                if k not in {"state", "node_key", "role_key", "attempt_no"}
            }
            value["status"] = span["state"]
            value["attributes"] = {
                **span["attributes"],
                **{k: span[k] for k in ("node_key", "role_key", "attempt_no")},
            }
            spans.append(value)
        closed = {
            "spans": spans,
            "events": collected,
            "links": final["links"],
            "nodes": final["nodes"],
            "final_status": "SUCCESS",
            "error_summary": None,
            "time_basis": "REALTIME",
            "logical_duration_ms": 600,
        }
    return {
        "nodes": final["nodes"],
        "spans": final["spans"],
        "links": final["links"],
        "events": collected,
        "closed_result": closed,
    }


async def fixed_execute(*, context, sink):
    last_seq = context["last_seq"]
    run_id = context["run_id"]
    for batch in copy.deepcopy(SAMPLES["journal_batches"]):
        batch.update(
            run_id=run_id,
            lease_epoch=context["lease_epoch"],
            expected_last_seq=last_seq,
        )
        batch["batch_id"] = str(uuid5(UUID(run_id), batch["batch_id"]))
        batch["checkpoint"].update(
            definition_hash=context["definition_hash"], journal_seq=last_seq
        )
        for event in batch["events"]:
            event["producer_event_id"] = str(
                uuid5(UUID(run_id), event["producer_event_id"])
            )
            if event["kind"] == "span.event":
                event["payload"]["event_id"] = str(
                    uuid5(UUID(run_id), event["payload"]["event_id"])
                )
        ack = await sink.commit(batch)
        last_seq = ack.last_seq


def main():
    from app.services import v2_runs

    action, worker_id = sys.argv[1:3]
    if action == "hold":
        owned = v2_runs.claim(worker_id)
        Path(sys.argv[3]).write_text(str(owned["run_id"]), encoding="ascii")
        # This is an explicit fault barrier; parent terminates only this process.
        import threading

        threading.Event().wait(60)
        return
    module = types.ModuleType("app.execution_v2")
    module.RealtimeClock = object
    module.execute_workflow = fixed_execute
    module.reduce_journal = lambda *, events: projection(events)
    sys.modules["app.execution_v2"] = module
    from app.worker.__main__ import work

    asyncio.run(work(worker_id, once=True))


if __name__ == "__main__":
    main()
