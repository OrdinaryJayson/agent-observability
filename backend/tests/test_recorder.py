from copy import deepcopy

import pytest

from app.recorder.recorder import TraceRecorder
from app.services.run_completion import validate_result
from app.simulator.runner import run_simulation


def simulation(count=8, failure_rate=0):
    return run_simulation(
        run_id="unused",
        trace_id="a" * 32,
        config={
            "min_spans": count,
            "max_spans": count,
            "failure_rate": failure_rate,
        },
    )


@pytest.mark.parametrize("count", [1, 2, 8, 105, 500])
@pytest.mark.parametrize("failure_rate", [0, 1])
def test_simulation_limits_and_status(count, failure_rate):
    result = simulation(count, failure_rate)
    validate_result(result.spans, result.events)
    assert len(result.spans) == count
    assert result.final_status == ("FAILED" if failure_rate else "SUCCESS")
    assert all(s["agent_id"] is None for s in result.spans)
    assert all(s["end_time"] >= s["start_time"] for s in result.spans)


def test_seed_reproduces_structure_and_tokens():
    a, b = simulation(), simulation()
    for x, y in zip(a.spans, b.spans):
        assert (x["span_name"], x["status"], x["input_tokens"], x["output_tokens"]) == (
            y["span_name"],
            y["status"],
            y["input_tokens"],
            y["output_tokens"],
        )


def test_recorder_closes_spans_and_records_errors():
    recorder = TraceRecorder(run_id="x", trace_id="a" * 32)
    with pytest.raises(RuntimeError):
        with recorder.span("root", "WORKFLOW"):
            with recorder.span("tool", "TOOL"):
                raise RuntimeError("sensitive text")
    result = recorder.result(final_status="FAILED", error_summary="failure")
    validate_result(result.spans, result.events)
    assert all(s["status"] == "ERROR" for s in result.spans)
    assert "sensitive text" not in str(result)


@pytest.mark.parametrize(
    "kind",
    ["duplicate", "two_roots", "missing", "cycle", "event", "token", "time", "size"],
)
def test_invalid_traces_rejected(kind):
    result = simulation()
    spans, events = deepcopy(result.spans), deepcopy(result.events)
    children = [s for s in spans if s["parent_span_id"] is not None]
    if kind == "duplicate":
        spans.append(spans[0])
    elif kind == "two_roots":
        children[0]["parent_span_id"] = None
    elif kind == "missing":
        children[0]["parent_span_id"] = "f" * 16
    elif kind == "cycle":
        children[0]["parent_span_id"] = children[1]["span_id"]
        children[1]["parent_span_id"] = children[0]["span_id"]
    elif kind == "event":
        events[0]["span_id"] = "f" * 16
    elif kind == "token":
        next(s for s in spans if s["operation_type"] != "LLM")["input_tokens"] = 5
    elif kind == "time":
        spans[0]["end_time"] = spans[0]["start_time"].replace(year=2000)
    elif kind == "size":
        spans *= 100
    with pytest.raises(ValueError):
        validate_result(spans, events)
