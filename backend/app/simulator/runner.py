import random
import time
from contextlib import nullcontext

from app.contracts.trace import SimulationResult
from app.recorder.recorder import TraceRecorder
from app.contracts.execution import SimulationConfig


def run_simulation(*, run_id: str, trace_id: str, config: dict) -> SimulationResult:
    cfg = SimulationConfig.model_validate(config)
    rng = random.Random(cfg.seed)
    count = rng.randint(cfg.min_spans, cfg.max_spans)
    recorder = TraceRecorder(run_id=run_id, trace_id=trace_id)
    failed = False
    roles = ["Research Agent", "Analysis Agent", "Review Agent"][: cfg.agent_count]
    with recorder.span(
        "Task Execution", "WORKFLOW", attributes={"scenario": cfg.scenario}
    ) as root:
        recorder.event("run.started", message="模拟执行开始")
        remaining = count - 1
        for role in roles:
            if remaining == 0:
                break
            with recorder.span(role, "AGENT"):
                remaining -= 1
                if remaining:
                    with recorder.span(
                        "Model reasoning",
                        "LLM",
                        provider="simulated",
                        model_name="mock-model",
                        input_tokens=rng.randint(10, 50),
                        output_tokens=rng.randint(5, 30),
                    ):
                        time.sleep(0.001)
                    remaining -= 1
        # If a run has only one span, its root still supports a simulated failure.
        for index in range(max(remaining, 1)):
            context = (
                recorder.span(f"Search {index + 1}", "TOOL", tool_name="mock_search")
                if remaining
                else nullcontext(root)
            )
            with context as item:
                if rng.random() < cfg.failure_rate:
                    failed = True
                    item.update(
                        status="ERROR",
                        error_type="SimulatedToolError",
                        error_message="模拟工具失败",
                    )
                    recorder.event(
                        "tool.failed", severity="ERROR", message="模拟工具失败"
                    )
                time.sleep(0.001)
        recorder.event("run.completed", message="模拟执行结束")
    return recorder.result(
        final_status="FAILED" if failed else "SUCCESS",
        error_summary="Simulated tool failed" if failed else None,
    )
