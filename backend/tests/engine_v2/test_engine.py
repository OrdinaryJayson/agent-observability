import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from uuid import uuid4

import pytest

from app.analysis_v2 import analyze_run
from app.contracts.trace import EventData, SpanData
from app.execution_v2 import (
    EngineError,
    RealtimeClock,
    VirtualClock,
    execute_workflow,
    reduce_journal,
    seal_interrupted,
    validate_workflow,
)
from app.execution_v2.memory import MemorySink
from app.execution_v2.engine import node_random
from app.execution_v2.protocol import digest, encoded
from app.execution_v2.recorder import IncrementalRecorder
from app.execution_v2.templates import workflow_templates


def context(definition, sink, *, mode="VIRTUAL", **config):
    return dict(
        run_id=sink.run_id,
        trace_id="a" * 32,
        definition=definition,
        definition_hash=digest(definition),
        config={"mode": mode, "unbound": True, **config},
        agent_bindings={},
        lease_epoch=sink.lease_epoch,
        checkpoint=deepcopy(sink.checkpoint),
        last_seq=sink.last_seq,
        clock=VirtualClock(datetime(2026, 11, 18, tzinfo=timezone.utc))
        if mode == "VIRTUAL"
        else RealtimeClock(),
    )


def execute(definition=None, sink=None, **config):
    definition = definition or workflow_templates()["parallel"]
    sink = sink or MemorySink(str(uuid4()))
    asyncio.run(
        execute_workflow(context=context(definition, sink, **config), sink=sink)
    )
    return sink, sink.projection()["closed_result"]


@pytest.mark.parametrize("name", ["research", "parallel", "quality"])
def test_templates_and_frozen_schema(name):
    definition = workflow_templates()[name]
    assert validate_workflow(definition) == {"valid": True, "errors": []}
    sink, result = execute(definition)
    assert result["final_status"] == "SUCCESS"
    for span in result["spans"]:
        SpanData.model_validate(span)
    for event in result["events"]:
        EventData.model_validate(event)
    assert sink.checkpoint["journal_seq"] == sink.last_seq
    assert not sink.checkpoint["open_spans"]
    assert all(
        len(batch["events"]) <= 100 and len(encoded(batch)) <= 512 * 1024
        for batch in sink.commit_calls
    )
    assert (
        len([span for span in result["spans"] if span["parent_span_id"] is None]) == 1
    )
    assert [event["seq"] for event in sink.events] == list(range(1, sink.last_seq + 1))


def test_parallel_and_capacity_wait_are_separate_from_critical_path():
    _, parallel = execute(max_parallelism=4)
    _, serial = execute(max_parallelism=1)
    assert parallel["logical_duration_ms"] == 600
    assert serial["logical_duration_ms"] == 900
    analysis = analyze_run(
        definition=workflow_templates()["parallel"], projection=serial
    )
    assert analysis["critical_path"]["duration_ms"] == 600
    assert analysis["scheduler_wait_ms"] == 300
    assert analysis["journal_seq"] > 0


def test_retry_backoff_does_not_delay_an_independent_branch():
    definition = workflow_templates()["parallel"]
    definition["nodes"][1]["config"].update(failure_probability=0.5, max_retries=1)
    definition["nodes"][2]["config"]["duration_ms"] = 350
    seed = next(
        seed
        for seed in range(100)
        if node_random(seed, "search_a", 1).random() < 0.5
        and node_random(seed, "search_a", 2).random() >= 0.5
    )
    _, result = execute(definition, seed=seed)
    other = next(
        span for span in result["spans"] if span["attributes"]["node_key"] == "search_b"
    )
    assert (other["end_time"] - other["start_time"]).total_seconds() * 1000 == 350
    assert result["logical_duration_ms"] == 700


def test_failed_branch_allows_an_inflight_independent_branch_to_close():
    definition = workflow_templates()["parallel"]
    definition["nodes"][1]["config"].update(failure_probability=1, max_retries=0)
    _, result = execute(definition)
    assert result["final_status"] == "FAILED"
    assert result["logical_duration_ms"] == 600
    other = next(
        span for span in result["spans"] if span["attributes"]["node_key"] == "search_b"
    )
    assert other["status"] == "SUCCESS"


def test_role_identity_tokens_and_zero_values():
    definition = workflow_templates()["research"]
    definition["nodes"][1]["config"]["failure_probability"] = 0
    definition["nodes"][2]["config"].update(input_tokens=0, output_tokens=0)
    sink = MemorySink(str(uuid4()))
    cfg = context(definition, sink)
    ids = {role["role_key"]: str(uuid4()) for role in definition["roles"]}
    cfg["agent_bindings"], cfg["config"]["unbound"] = ids, False
    asyncio.run(execute_workflow(context=cfg, sink=sink))
    spans = sink.projection()["closed_result"]["spans"]
    for span in spans:
        role = span["attributes"]["role_key"]
        assert str(span["agent_id"]) == ids[role] if role else span["agent_id"] is None
        if span["operation_type"] != "LLM":
            assert span["input_tokens"] is span["output_tokens"] is None
    llm = next(span for span in spans if span["attributes"]["node_key"] == "analyze")
    assert llm["input_tokens"] == llm["output_tokens"] == 0


@pytest.mark.parametrize("route,skipped", [("PASS", "revise"), ("FAIL", "accept")])
def test_branch_and_merge(route, skipped):
    definition = workflow_templates()["quality"]
    definition["nodes"][2]["config"]["result"] = route
    _, result = execute(definition)
    assert (
        next(node for node in result["nodes"] if node["node_key"] == skipped)["state"]
        == "SKIPPED"
    )
    assert not any(
        span["attributes"]["node_key"] == skipped for span in result["spans"]
    )
    assert (
        next(node for node in result["nodes"] if node["node_key"] == "merge")["state"]
        == "SUCCESS"
    )


def test_condition_can_merge_two_empty_branches_at_the_same_node():
    definition = workflow_templates()["quality"]
    definition["nodes"] = [
        node
        for node in definition["nodes"]
        if node["node_key"] not in {"accept", "revise"}
    ]
    definition["edges"] = [
        edge
        for edge in definition["edges"]
        if edge["source"] not in {"accept", "revise", "gate"}
    ]
    definition["edges"].extend(
        {"source": "gate", "target": "merge", "route": route}
        for route in ("PASS", "FAIL")
    )
    assert validate_workflow(definition)["valid"]
    assert execute(definition)[1]["final_status"] == "SUCCESS"


def test_retry_and_unrecovered_failure():
    definition = workflow_templates()["research"]
    definition["nodes"][1]["config"].update(failure_probability=1, max_retries=2)
    _, result = execute(definition)
    assert result["final_status"] == "FAILED"
    attempts = [
        span for span in result["spans"] if span["attributes"]["node_key"] == "retrieve"
    ]
    assert [span["attributes"]["attempt_no"] for span in attempts] == [1, 2, 3]
    assert all(span["status"] == "ERROR" for span in attempts)
    assert result["logical_duration_ms"] == 1200
    definition["nodes"][1]["config"].update(failure_probability=0.5, max_retries=2)
    recovered = None
    for seed in range(30):
        _, candidate = execute(definition, seed=seed)
        if candidate["final_status"] == "SUCCESS" and any(
            span["status"] == "ERROR" for span in candidate["spans"]
        ):
            recovered = seed
            break
    assert recovered is not None


def test_seed_is_independent_of_parallelism():
    definition = workflow_templates()["parallel"]
    for node in definition["nodes"]:
        if node["type"] == "RETRIEVAL":
            node["config"].update(failure_probability=0.25, max_retries=2)
    results = [execute(definition, seed=19, max_parallelism=p)[1] for p in (1, 4)]
    signatures = [
        sorted(
            (
                span["attributes"]["node_key"],
                span["attributes"]["attempt_no"],
                span["status"],
            )
            for span in result["spans"]
            if span["attributes"]["node_key"]
        )
        for result in results
    ]
    assert signatures[0] == signatures[1]


def test_lost_ack_and_failure_before_commit_are_idempotent():
    sink = MemorySink(str(uuid4()))
    sink.lose_ack, sink.fail_before_commit = 1, 1
    sink, result = execute(sink=sink)
    assert result["final_status"] == "SUCCESS"
    assert sink.commit_calls[0] == sink.commit_calls[1] == sink.commit_calls[2]
    assert len({event["producer_event_id"] for event in sink.events}) == len(
        sink.events
    )
    first = deepcopy(sink.commit_calls[0])
    first["events"][0]["payload"]["span_name"] = "changed"
    with pytest.raises(EngineError, match="different content"):
        asyncio.run(sink.commit(first))


class CrashingSink(MemorySink):
    async def commit(self, batch):
        ack = await super().commit(batch)
        if any(
            span["node_key"] == "search_b" for span in self.checkpoint["open_spans"]
        ):
            self.lease_valid = False
            raise EngineError("LEASE_LOST", "Injected process crash")
        return ack


def test_worker_recovery_closes_inflight_and_keeps_committed_success():
    sink = CrashingSink(str(uuid4()))
    definition = workflow_templates()["parallel"]
    with pytest.raises(EngineError, match="crash"):
        execute(definition, sink=sink)
    successful = set(sink.checkpoint["completed_span_ids"])
    sink.__class__ = MemorySink
    sink.recover()
    resumed = context(definition, sink)
    resumed["clock"] = VirtualClock(datetime(2027, 1, 1, tzinfo=timezone.utc))
    asyncio.run(execute_workflow(context=resumed, sink=sink))
    result = sink.projection()["closed_result"]
    root = next(span for span in result["spans"] if span["parent_span_id"] is None)
    assert (root["end_time"] - root["start_time"]).total_seconds() * 1000 == result[
        "logical_duration_ms"
    ]
    assert result["final_status"] == "SUCCESS"
    assert successful <= {span["span_id"] for span in result["spans"]}
    assert any(span["error_type"] == "WorkerLost" for span in result["spans"])
    start = [
        span for span in result["spans"] if span["attributes"]["node_key"] == "start"
    ]
    assert len(start) == 1
    assert sink.checkpoint["journal_seq"] == sink.last_seq


def test_checkpoint_hash_and_watermark_rejected():
    sink = CrashingSink(str(uuid4()))
    with pytest.raises(EngineError):
        execute(sink=sink)
    sink.__class__ = MemorySink
    sink.recover()
    cfg = context(workflow_templates()["parallel"], sink)
    cfg["checkpoint"]["definition_hash"] = "0" * 64
    with pytest.raises(EngineError, match="mismatch"):
        asyncio.run(execute_workflow(context=cfg, sink=sink))


def test_realtime_wait_is_real_and_cancel_interrupts():
    class CancelSink(MemorySink):
        async def control(self):
            if time.monotonic() - beginning > 0.12:
                self.cancel_requested = True
            return await super().control()

    sink = CancelSink(str(uuid4()))
    beginning = time.monotonic()
    _, result = execute(sink=sink, mode="REALTIME")
    elapsed = time.monotonic() - beginning
    assert 0.1 <= elapsed < 2
    assert result["final_status"] == "CANCELLED"
    assert not any(span["end_time"] is None for span in result["spans"])
    assert any(node["state"] == "CANCELLED" for node in result["nodes"])


def test_task_local_recorder_context():
    async def main():
        recorder = IncrementalRecorder(VirtualClock())
        root = recorder.start("Root", "WORKFLOW")
        parents = [
            recorder.start(str(index), "AGENT", parent_span_id=root)
            for index in range(4)
        ]

        async def child(parent):
            with recorder.under(parent):
                await asyncio.sleep(0)
                span_id = recorder.start("Tool", "TOOL")
                assert recorder.open_spans[span_id]["parent_span_id"] == parent
                recorder.finish(span_id)

        await asyncio.gather(*(child(parent) for parent in parents))

    asyncio.run(main())


def test_frozen_journal_reduction_and_sealing():
    path = Path(__file__).resolve().parents[3] / "contracts/v2/examples.json"
    examples = json.loads(path.read_text(encoding="utf-8"))
    projection = reduce_journal(events=examples["journal"])
    assert len(projection["closed_result"]["spans"]) == 7
    cut = examples["journal"][:8]
    first = seal_interrupted(
        events=cut,
        reason="WorkerLost",
        ended_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
    )
    second = seal_interrupted(
        events=cut,
        reason="WorkerLost",
        ended_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
    )
    assert first == second
    assert first["final_status"] == "FAILED"
    assert all(
        span["status"] == "ERROR"
        for span in first["spans"]
        if span["attributes"]["node_key"] in {"search_a", "search_b"}
    )
    broken = deepcopy(examples["journal"])
    broken[3]["seq"] += 10
    with pytest.raises(ValueError, match="contiguous"):
        reduce_journal(events=broken)
