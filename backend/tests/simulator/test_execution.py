from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest

from app.recorder.recorder import TraceRecorder
from app.services.run_completion import validate_result
from app.simulator.runner import run_simulation


def simulate(**config):
    return run_simulation(run_id=str(uuid4()), trace_id="a" * 32, config=config)


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 8, 105, 500])
@pytest.mark.parametrize("agent_count", [1, 2, 3])
def test_binding_order_inheritance_and_limits(count, agent_count):
    ids = [uuid4() for _ in range(agent_count)]
    result = simulate(
        min_spans=count,
        max_spans=count,
        agent_count=agent_count,
        agent_ids=[str(value) for value in ids],
        failure_rate=0,
    )
    spans, events = validate_result(result.spans, result.events)
    assert len(spans) == count
    assert result.final_status == "SUCCESS"
    by_id = {span["span_id"]: span for span in spans}
    root = next(span for span in spans if span["parent_span_id"] is None)
    assert root["operation_type"] == "WORKFLOW"
    assert root["agent_id"] is None
    agents = sorted(
        (span for span in spans if span["operation_type"] == "AGENT"),
        key=lambda span: span["start_time"],
    )
    assert [span["agent_id"] for span in agents] == ids[: min(agent_count, count - 1)]
    for span in spans:
        assert span["start_time"].utcoffset() == timedelta(0)
        assert span["end_time"].utcoffset() == timedelta(0)
        if span["operation_type"] in {"LLM", "TOOL"}:
            parent = by_id[span["parent_span_id"]]
            assert parent["operation_type"] == "AGENT"
            assert span["agent_id"] == parent["agent_id"]
            assert (
                parent["start_time"]
                <= span["start_time"]
                <= span["end_time"]
                <= parent["end_time"]
            )
        if span["operation_type"] != "LLM":
            assert span["input_tokens"] is span["output_tokens"] is None
    for event in events:
        span = by_id[event["span_id"]]
        assert span["start_time"] <= event["occurred_at"] <= span["end_time"]
    assert len(events) <= 2000


def structure(result):
    positions = {span["span_id"]: index for index, span in enumerate(result.spans)}
    spans = [
        {
            key: value
            for key, value in span.items()
            if key not in {"span_id", "parent_span_id", "start_time", "end_time"}
        }
        | {"parent": positions.get(span["parent_span_id"])}
        for span in result.spans
    ]
    events = [
        {
            key: value
            for key, value in event.items()
            if key not in {"event_id", "span_id", "occurred_at"}
        }
        | {"span": positions[event["span_id"]]}
        for event in result.events
    ]
    return spans, events, result.final_status, result.error_summary


@pytest.mark.parametrize("seed", range(20))
def test_seed_failure_retry_and_budget(seed):
    config = dict(min_spans=1, max_spans=500, failure_rate=0.25, seed=seed)
    first, second = simulate(**config), simulate(**config)
    assert structure(first) == structure(second)
    validate_result(first.spans, first.events)
    assert 1 <= len(first.spans) <= 500
    assert len(first.events) <= 2000
    assert {span["span_id"] for span in first.spans}.isdisjoint(
        span["span_id"] for span in second.spans
    )
    operations = [
        span for span in first.spans if span["operation_type"] in {"LLM", "TOOL"}
    ]
    groups = {}
    for span in operations:
        key = span["parent_span_id"], span["attributes"]["operation_index"]
        groups.setdefault(key, []).append(span)
    for group in groups.values():
        assert [span["attributes"]["retry_count"] for span in group] in ([0], [0, 1])
        if len(group) == 2:
            assert group[0]["status"] == "ERROR"


def test_fixed_recovered_seed():
    result = simulate(min_spans=8, max_spans=8, agent_count=1, failure_rate=0.1, seed=6)
    assert result.final_status == "SUCCESS"
    assert any(span["status"] == "ERROR" for span in result.spans)
    assert any(span["attributes"].get("retry_count") == 1 for span in result.spans)


@pytest.mark.parametrize("agent_ids", [None, "omitted"])
def test_unbound_compatibility(agent_ids):
    config = {"failure_rate": 0}
    if agent_ids != "omitted":
        config["agent_ids"] = agent_ids
    assert all(span["agent_id"] is None for span in simulate(**config).spans)


def test_no_retry_budget_and_unrecoverable_failure():
    result = simulate(
        min_spans=3, max_spans=3, agent_count=1, failure_rate=0.99, seed=42
    )
    assert result.final_status == "FAILED"
    assert len(result.spans) == 3
    assert not any(event["event_name"] == "operation.retry" for event in result.events)
    result = simulate(min_spans=500, max_spans=500, failure_rate=1)
    assert result.final_status == "FAILED"
    assert len(result.spans) == 500
    assert not any(span["attributes"].get("retry_count") for span in result.spans)


def test_independent_recorders_concurrently():
    barrier = Barrier(8)

    def record(index):
        recorder = TraceRecorder(run_id=str(index), trace_id=f"{index:032x}")
        with recorder.span("root", "WORKFLOW"):
            barrier.wait(timeout=5)
            with recorder.span("agent", "AGENT", agent_id=uuid4()):
                with recorder.span("tool", "TOOL"):
                    recorder.event("tool.completed")
        result = recorder.result(final_status="SUCCESS", error_summary=None)
        validate_result(result.spans, result.events)
        return result

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(record, range(8)))
    assert len({span["span_id"] for result in results for span in result.spans}) == 24
    assert all(len(result.events) == 1 for result in results)


def test_recorder_caps_roots_and_result_snapshot():
    recorder = TraceRecorder(run_id="x", trace_id="a" * 32)
    with recorder.span("root", "WORKFLOW"):
        for _ in range(499):
            with recorder.span("tool", "TOOL"):
                pass
        with pytest.raises(ValueError, match="500"):
            with recorder.span("extra", "TOOL"):
                pass
        for _ in range(2000):
            recorder.event("tick")
        with pytest.raises(ValueError, match="2000"):
            recorder.event("overflow")
    result = recorder.result(final_status="SUCCESS", error_summary=None)
    validate_result(result.spans, result.events)
    result.spans[0]["attributes"]["changed"] = True
    assert recorder.spans[0]["attributes"] == {}
    other = TraceRecorder(run_id="y", trace_id="b" * 32)
    with pytest.raises(ValueError, match="empty"):
        other.result(final_status="SUCCESS", error_summary=None)
    with other.span("root", "WORKFLOW"):
        with pytest.raises(ValueError, match="open"):
            other.result(final_status="SUCCESS", error_summary=None)
    with pytest.raises(ValueError, match="one root"):
        with other.span("second root", "WORKFLOW"):
            pass


def test_event_limit_does_not_mask_original_exception():
    recorder = TraceRecorder(run_id="x", trace_id="a" * 32)
    with pytest.raises(RuntimeError, match="original"):
        with recorder.span("root", "WORKFLOW"):
            for _ in range(2000):
                recorder.event("tick")
            raise RuntimeError("original")
    result = recorder.result(final_status="FAILED", error_summary="failure")
    validate_result(result.spans, result.events)
