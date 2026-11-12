"""Seeded research execution with bounded, single-attempt recovery."""

import random

from app.contracts.execution import SimulationConfig
from app.contracts.trace import SimulationResult
from app.recorder.recorder import TraceRecorder


def _mark_failure(recorder: TraceRecorder, item: dict, operation: str) -> None:
    item.update(
        status="ERROR",
        error_type=f"Simulated{operation.title()}Error",
        error_message="模拟操作失败",
    )
    recorder.event(
        f"{operation.lower()}.failed", severity="ERROR", message="模拟操作失败"
    )


def _operations(
    recorder: TraceRecorder, budget: int, cfg: SimulationConfig, rng: random.Random
) -> bool:
    """Consume exactly budget spans, including retries. Return unresolved failure."""
    failed = False
    index = 0
    while budget:
        operation = "LLM" if index == 0 else "TOOL"
        retry_count = 0
        while True:
            fields = (
                {
                    "provider": "simulated",
                    "model_name": "mock-model",
                    "input_tokens": rng.randint(10, 50),
                    "output_tokens": rng.randint(5, 30),
                }
                if operation == "LLM"
                else {"tool_name": "mock_search"}
            )
            with recorder.span(
                "Model reasoning" if operation == "LLM" else f"Search {index}",
                operation,
                attributes={
                    "scenario": cfg.scenario,
                    "operation_index": index,
                    "retry_count": retry_count,
                },
                **fields,
            ) as item:
                recorder.event(f"{operation.lower()}.started", message="模拟操作开始")
                error = rng.random() < cfg.failure_rate
                if error:
                    _mark_failure(recorder, item, operation)
                else:
                    recorder.event(
                        f"{operation.lower()}.completed", message="模拟操作完成"
                    )
            budget -= 1
            if error and 0 < cfg.failure_rate < 1 and retry_count == 0 and budget:
                recorder.event(
                    "operation.retry",
                    severity="WARN",
                    message="模拟操作重试",
                    attributes={"operation_index": index, "retry_count": 1},
                )
                retry_count = 1
                continue
            failed |= error
            break
        index += 1
    return failed


def run_simulation(*, run_id: str, trace_id: str, config: dict) -> SimulationResult:
    cfg = SimulationConfig.model_validate(config)
    rng = random.Random(cfg.seed)
    count = rng.randint(cfg.min_spans, cfg.max_spans)
    recorder = TraceRecorder(run_id=run_id, trace_id=trace_id)
    failed = False
    roles = ["Research Agent", "Analysis Agent", "Review Agent"]
    role_count = min(cfg.agent_count, count - 1)
    with recorder.span(
        "Task Execution", "WORKFLOW", attributes={"scenario": cfg.scenario}
    ) as root:
        recorder.event("run.started", message="模拟执行开始")
        for index in range(role_count):
            # Split the total budget across roles before allowing any retry.
            role_budget = (count - 1) // role_count + (index < (count - 1) % role_count)
            agent_id = cfg.agent_ids[index] if cfg.agent_ids else None
            with recorder.span(roles[index], "AGENT", agent_id=agent_id) as agent:
                recorder.event("agent.started", message=roles[index])
                role_failed = _operations(recorder, role_budget - 1, cfg, rng)
                if role_budget == 1 and rng.random() < cfg.failure_rate:
                    _mark_failure(recorder, agent, "agent")
                    role_failed = True
                if role_failed:
                    agent.update(
                        status="ERROR",
                        error_type="SimulatedAgentError",
                        error_message="模拟角色执行失败",
                    )
                failed |= role_failed
                recorder.event("agent.completed", message=roles[index])
            if index + 1 < role_count:
                recorder.event(
                    "agent.handoff",
                    message=roles[index + 1],
                    attributes={"from_role": roles[index], "to_role": roles[index + 1]},
                )
        if count == 1 and rng.random() < cfg.failure_rate:
            _mark_failure(recorder, root, "workflow")
            failed = True
        if failed:
            root.update(
                status="ERROR",
                error_type="SimulatedWorkflowError",
                error_message="模拟任务执行失败",
            )
        recorder.event(
            "run.completed",
            severity="ERROR" if failed else "INFO",
            message="模拟执行失败" if failed else "模拟执行结束",
        )
    return recorder.result(
        final_status="FAILED" if failed else "SUCCESS",
        error_summary="Simulated operation failed" if failed else None,
    )
