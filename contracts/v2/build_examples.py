"""Rebuild synthetic v2 design artifacts. No network, database or app imports."""

import copy
import hashlib
import json
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent
UUID_SCHEMA = {"type": "string", "format": "uuid"}
TIME = {"type": "string", "format": "date-time"}
HEX = {"type": "string", "pattern": "^[0-9a-f]{16}$"}
KEY = {"type": "string", "pattern": "^(?!sys_)[a-z][a-z0-9_]{0,49}$"}
OBJECT = {"type": "object"}
NULL = {"type": "null"}


def obj(properties, required=None):
    return {"type": "object", "additionalProperties": False,
            "properties": properties,
            "required": list(properties) if required is None else required}


def array(items, minimum=0, maximum=None):
    value = {"type": "array", "items": items, "minItems": minimum}
    if maximum is not None:
        value["maxItems"] = maximum
    return value


def nullable(value):
    return {"anyOf": [value, NULL]}


def enum(*values):
    return {"enum": list(values)}


def integer(low=0, high=None):
    value = {"type": "integer", "minimum": low}
    if high is not None:
        value["maximum"] = high
    return value


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def node(key, kind, role=None, **config):
    return {"node_key": key, "type": kind, "name": key,
            "role_key": role, "config": config}


def edge(source, target, route="ALWAYS"):
    return {"source": source, "target": target, "route": route}


def schemas():
    operation = obj({"duration_ms": integer(100, 1500),
                     "failure_probability": {"type": "number", "minimum": 0, "maximum": 1},
                     "max_retries": integer(0, 2)})
    llm = copy.deepcopy(operation)
    llm["properties"].update({"input_tokens": integer(0, 100000),
                              "output_tokens": integer(0, 100000)})
    common = {"node_key": KEY, "name": {"type": "string", "minLength": 1, "maxLength": 100},
              "role_key": nullable(KEY)}
    choices = []
    for kind in ("START", "END", "LLM", "TOOL", "RETRIEVAL", "MERGE", "CONDITION"):
        config = llm if kind == "LLM" else operation if kind in ("TOOL", "RETRIEVAL") else (
            obj({"result": enum("PASS", "FAIL", "SEEDED")}) if kind == "CONDITION" else obj({}))
        choices.append(obj({**common, "type": {"const": kind}, "config": config}))
    workflow = obj({"schema_version": {"const": "2.0"},
                    "scenario": enum("RESEARCH_PIPELINE", "PARALLEL_RETRIEVAL", "QUALITY_GATE"),
                    "roles": array(obj({"role_key": KEY, "name": {"type": "string", "minLength": 1, "maxLength": 100}}), 0, 8),
                    "nodes": array({"oneOf": choices}, 2, 50),
                    "edges": array(obj({"source": KEY, "target": KEY, "route": enum("ALWAYS", "PASS", "FAIL")}), 1, 100)})
    workflow.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                     "$id": "urn:agent-observability:v2:workflow", "title": "WorkflowDefinition v2"})
    write("workflow.schema.json", workflow)

    token = nullable(integer(0, 2147483647))
    span_open = obj({"span_id": HEX, "parent_span_id": nullable(HEX), "agent_id": nullable(UUID_SCHEMA),
                     "operation_type": enum("AGENT", "LLM", "TOOL", "RETRIEVAL", "WORKFLOW", "OTHER"),
                     "span_name": {"type": "string", "minLength": 1, "maxLength": 200},
                     "node_key": nullable(KEY), "role_key": nullable(KEY),
                     "attempt_no": integer(1), "start_time": TIME, "attributes": OBJECT})
    finish = obj({"span_id": HEX, "status": enum("SUCCESS", "ERROR"), "end_time": TIME,
                  "input_tokens": token, "output_tokens": token,
                  "provider": nullable({"type": "string", "maxLength": 80}),
                  "model_name": nullable({"type": "string", "maxLength": 120}),
                  "tool_name": nullable({"type": "string", "maxLength": 120}),
                  "error_type": nullable({"type": "string", "maxLength": 100}),
                  "error_message": nullable({"type": "string"})})
    event_data = obj({"event_id": UUID_SCHEMA, "span_id": HEX,
                      "event_name": {"type": "string", "minLength": 1, "maxLength": 100},
                      "severity": enum("TRACE", "DEBUG", "INFO", "WARN", "ERROR"),
                      "message": nullable({"type": "string"}), "occurred_at": TIME, "attributes": OBJECT})
    link = obj({"source_span_id": HEX, "target_span_id": HEX,
                "link_type": enum("DEPENDS_ON", "RETRY_OF", "HANDOFF")})
    checkpoint = obj({"checkpoint_version": {"const": 1},
                      "definition_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                      "clock_mode": enum("REALTIME", "VIRTUAL"),
                      "logical_time_ms": {"type": "number", "minimum": 0},
                      "node_states": {"type": "object", "propertyNames": KEY, "additionalProperties": obj({
                          "state": enum("PENDING", "RUNNING", "SUCCESS", "ERROR", "SKIPPED", "CANCELLED"),
                          "attempt_no": integer(), "result": nullable(enum("PASS", "FAIL")),
                          "span_ids": array(HEX, 0, 500)})},
                      "attempts": array(obj({"node_key": KEY, "attempt_no": integer(1), "span_id": HEX,
                                             "state": enum("RUNNING", "SUCCESS", "ERROR")}), 0, 500),
                      "open_spans": array({"$ref": "#/$defs/span_open"}, 0, 500),
                      "completed_span_ids": array(HEX, 0, 500),
                      "resolved_routes": {"type": "object", "propertyNames": KEY,
                                          "additionalProperties": enum("PASS", "FAIL")},
                      "journal_seq": integer()})
    payloads = {"span.started": span_open, "span.finished": finish, "span.event": event_data,
                "link.created": link, "node.skipped": obj({"node_key": KEY, "reason": {"type": "string", "minLength": 1}}),
                "checkpoint.saved": obj({"checkpoint_version": {"const": 1}})}
    producers = [obj({"producer_event_id": UUID_SCHEMA, "kind": {"const": kind},
                      "payload": payload, "occurred_at": TIME}) for kind, payload in payloads.items()]
    batch = obj({"protocol_version": {"const": "2.0"}, "run_id": UUID_SCHEMA,
                 "batch_id": UUID_SCHEMA, "lease_epoch": integer(1), "expected_last_seq": integer(),
                 "events": array({"oneOf": producers}, 1, 100), "checkpoint": {"$ref": "#/$defs/checkpoint"},
                 "terminal": nullable(obj({"status": enum("SUCCESS", "FAILED", "CANCELLED"),
                                           "error_summary": nullable({"type": "string"})}))})
    batch.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                  "$id": "urn:agent-observability:v2:journal-batch", "title": "JournalBatch v2",
                  "$defs": {"span_open": span_open, "checkpoint": checkpoint}})
    write("journal-batch.schema.json", batch)


def artifacts():
    wid, vid, tid, rid, aid, did, eid = [str(UUID(f"{n}" * 8 + "-" + f"{n}" * 4 + "-4" + f"{n}" * 3 + "-8" + f"{n}" * 3 + "-" + f"{n}" * 12)) for n in range(1, 8)]
    t0, t1 = "2026-11-16T00:00:00Z", "2026-11-16T00:00:00.600Z"
    parallel = {"schema_version": "2.0", "scenario": "PARALLEL_RETRIEVAL",
                "roles": [{"role_key": "researcher", "name": "检索角色"}],
                "nodes": [node("start", "START"), node("search_a", "RETRIEVAL", "researcher", duration_ms=300, failure_probability=0, max_retries=1),
                          node("search_b", "RETRIEVAL", "researcher", duration_ms=600, failure_probability=0, max_retries=1),
                          node("merge", "MERGE"), node("end", "END")],
                "edges": [edge("start", "search_a"), edge("start", "search_b"), edge("search_a", "merge"), edge("search_b", "merge"), edge("merge", "end")]}
    research = {"schema_version": "2.0", "scenario": "RESEARCH_PIPELINE",
                "roles": [{"role_key": key, "name": key} for key in ("researcher", "analyst", "reviewer")],
                "nodes": [node("start", "START"), node("retrieve", "RETRIEVAL", "researcher", duration_ms=300, failure_probability=0.1, max_retries=1),
                          node("analyze", "LLM", "analyst", duration_ms=500, failure_probability=0, max_retries=1, input_tokens=50, output_tokens=20),
                          node("review", "LLM", "reviewer", duration_ms=300, failure_probability=0, max_retries=0, input_tokens=30, output_tokens=10), node("end", "END")],
                "edges": [edge("start", "retrieve"), edge("retrieve", "analyze"), edge("analyze", "review"), edge("review", "end")]}
    quality = {"schema_version": "2.0", "scenario": "QUALITY_GATE", "roles": [{"role_key": "writer", "name": "生成角色"}],
               "nodes": [node("start", "START"), node("generate", "LLM", "writer", duration_ms=300, failure_probability=0, max_retries=0, input_tokens=20, output_tokens=10),
                         node("gate", "CONDITION", result="PASS"), node("accept", "TOOL", "writer", duration_ms=100, failure_probability=0, max_retries=0),
                         node("revise", "LLM", "writer", duration_ms=300, failure_probability=0, max_retries=1, input_tokens=20, output_tokens=10),
                         node("merge", "MERGE"), node("end", "END")],
               "edges": [edge("start", "generate"), edge("generate", "gate"), edge("gate", "accept", "PASS"), edge("gate", "revise", "FAIL"),
                         edge("accept", "merge"), edge("revise", "merge"), edge("merge", "end")]}
    digest = hashlib.sha256(json.dumps(parallel, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    config = {"version_id": vid, "agent_bindings": {"researcher": aid}, "unbound": False, "seed": 42,
              "mode": "REALTIME", "max_parallelism": 4, "priority": 0, "retry_of_run_id": None, "dataset_id": None}
    spans = {}
    for number, name, kind, parent, role in [(1, None, "WORKFLOW", None, None), (2, None, "AGENT", 1, "researcher"),
                                            (3, "start", "WORKFLOW", 1, None), (4, "search_a", "RETRIEVAL", 2, "researcher"),
                                            (5, "search_b", "RETRIEVAL", 2, "researcher"), (6, "merge", "WORKFLOW", 1, None), (7, "end", "WORKFLOW", 1, None)]:
        spans[number] = {"span_id": f"{number:016x}", "parent_span_id": f"{parent:016x}" if parent else None,
                         "agent_id": aid if role else None, "operation_type": kind,
                         "span_name": name or ("Task Execution" if number == 1 else "检索角色"),
                         "node_key": name, "role_key": role, "attempt_no": 1,
                         "start_time": t1 if number in (6, 7) else t0, "attributes": {}}
    journal = []

    def emit(kind, payload, when=t0):
        seq = len(journal) + 1
        event = {"run_id": rid, "seq": seq, "producer_event_id": str(UUID(int=1000 + seq)),
                 "kind": kind, "payload": copy.deepcopy(payload), "occurred_at": when, "recorded_at": when}
        journal.append(event)

    def opened(number):
        emit("span.started", spans[number], spans[number]["start_time"])

    def finished(number, when):
        emit("span.finished", {"span_id": spans[number]["span_id"], "status": "SUCCESS", "end_time": when,
                               "input_tokens": None, "output_tokens": None, "provider": None, "model_name": None,
                               "tool_name": "mock_retrieval" if number in (4, 5) else None,
                               "error_type": None, "error_message": None}, when)

    emit("run.queued", {"execution_state": "QUEUED"})
    emit("run.started", {"lease_epoch": 1})
    for number in (1, 2, 3):
        opened(number)
    finished(3, t0)
    opened(4)
    opened(5)
    first_part = copy.deepcopy(journal[2:])
    midpoint = len(journal)
    for number in (4, 5):
        completed_at = "2026-11-16T00:00:00.300Z" if number == 4 else t1
        finished(number, completed_at)
        emit("span.event", {"event_id": str(UUID(int=2000 + number)), "span_id": spans[number]["span_id"],
                            "event_name": "retrieval.completed", "severity": "INFO", "message": "合成协议事件",
                            "occurred_at": completed_at, "attributes": {}}, completed_at)
    for number in (6, 7):
        opened(number)
        finished(number, t1)
    number_by_key = {value["node_key"]: number for number, value in spans.items() if value["node_key"]}
    links = []
    for item in parallel["edges"]:
        link = {"source_span_id": spans[number_by_key[item["source"]]]["span_id"],
                "target_span_id": spans[number_by_key[item["target"]]]["span_id"], "link_type": "DEPENDS_ON"}
        links.append(link)
        emit("link.created", link, t1)
    finished(2, t1)
    finished(1, t1)
    emit("checkpoint.saved", {"checkpoint_version": 1}, t1)
    before_terminal = len(journal)
    emit("run.finished", {"status": "SUCCESS", "error_summary": None, "projection_complete": True, "final_seq": before_terminal + 1}, t1)

    def checkpoint(final):
        active = (1, 2, 4, 5) if not final else ()
        complete = (3,) if not final else tuple(spans)
        states = {}
        for item in parallel["nodes"]:
            key, number = item["node_key"], number_by_key[item["node_key"]]
            state = "SUCCESS" if final or key == "start" else "RUNNING" if number in active else "PENDING"
            states[key] = {"state": state, "attempt_no": 0 if state == "PENDING" else 1,
                           "result": None, "span_ids": [] if state == "PENDING" else [spans[number]["span_id"]]}
        return {"checkpoint_version": 1, "definition_hash": digest, "clock_mode": "REALTIME",
                "logical_time_ms": 600 if final else 0, "node_states": states,
                "attempts": [{"node_key": key, "attempt_no": 1, "span_id": value["span_ids"][0], "state": value["state"]}
                             for key, value in states.items() if value["span_ids"]],
                "open_spans": [spans[n] for n in active], "completed_span_ids": [spans[n]["span_id"] for n in complete],
                "resolved_routes": {}, "journal_seq": before_terminal if final else midpoint}

    batches = []
    for final, items in [(False, first_part), (True, journal[midpoint:before_terminal])]:
        pending_checkpoint = checkpoint(final)
        pending_checkpoint["journal_seq"] = midpoint if final else 2
        batches.append({"protocol_version": "2.0", "run_id": rid, "batch_id": str(UUID(int=3000 + int(final))),
                        "lease_epoch": 1, "expected_last_seq": midpoint if final else 2,
                        "events": [{k: v for k, v in item.items() if k not in ("run_id", "seq", "recorded_at")} for item in items],
                        "checkpoint": pending_checkpoint, "terminal": {"status": "SUCCESS", "error_summary": None} if final else None})
    run = {"run_id": rid, "task_id": tid, "trace_id": "a" * 32, "source_type": "SIMULATED", "status": "SUCCESS",
           "started_at": t0, "ended_at": t1, "error_summary": None, "created_at": t0,
           "version_id": vid, "workflow_name": "并行检索演示", "version_no": 1, "mode": "REALTIME",
           "execution_state": "FINISHED", "queued_at": t0, "execution_started_at": t0, "execution_ended_at": t1,
           "queue_duration_ms": 0, "execution_duration_ms": 600, "logical_duration_ms": 600,
           "last_seq": len(journal), "cancel_requested_at": None, "recovery_count": 0,
           "span_count": len(spans), "error_count": 0, "progress": 1}
    closed = {}
    for item in journal:
        if item["kind"] == "span.finished":
            closed[item["payload"]["span_id"]] = item["payload"]
    live_spans = [{**value, **{k: v for k, v in closed[value["span_id"]].items() if k != "status"}, "state": "SUCCESS"} for value in spans.values()]
    snapshot = {"run": run, "seq": len(journal), "nodes": [{"node_key": key, **{k: v for k, v in value.items() if k != "result"}} for key, value in checkpoint(True)["node_states"].items()],
                "spans": live_spans, "links": links, "event_count": 2, "projection_complete": True}
    analysis = {"algorithm_version": "2.0", "journal_seq": len(journal), "time_basis": "REALTIME",
                "critical_path": {"node_keys": ["start", "search_b", "merge", "end"], "duration_ms": 600},
                "self_times": [{"span_id": value["span_id"], "duration_ms": 300 if number == 4 else 600 if number == 5 else 0} for number, value in spans.items()],
                "retry_overhead_ms": 0, "scheduler_wait_ms": 0, "recovery_pause_ms": 0,
                "findings": [], "limitations": ["合成样例，不是性能测量", "INSUFFICIENT_BASELINE"]}
    cases = ["INDEX_SELECTIVITY", "JSONB_GIN", "PAGINATION", "AGGREGATION", "MVCC_ISOLATION", "QUEUE_CONTENTION"]
    parameters = [{"query": "TRACE", "selectivity": 0.01}, {"selectivity": 0.01}, {"rank": 10000, "limit": 50},
                  {"window_days": 30}, {"schedule": "WRITE_SKEW"}, {"claimers": 4, "jobs": 1000}]
    dataset = {"dataset_id": did, "name": "BENCH_100K 合成协议样例", "purpose": "BENCHMARK", "state": "READY",
               "seed": 42, "config": {"profile": "BENCH_100K"}, "actual_counts": {"runs": 200, "spans": 100000},
               "content_hash": "0" * 64, "generator_version": "2.0-synthetic", "created_at": t0, "completed_at": t1}
    example = {"note": "全部为合成协议样例；数值不是实测、记录不代表已实现。Schema形状+本文语义共同约束实现。",
               "ids": {"workflow_id": wid, "version_id": vid, "task_id": tid, "run_id": rid, "agent_id": aid, "dataset_id": did, "experiment_id": eid},
               "workflow_definitions": {"parallel": parallel, "research": research, "quality": quality},
               "workflow": {"workflow_id": wid, "name": "并行检索演示", "description": None, "draft": parallel,
                            "revision": 1, "archived_at": None, "created_at": t0, "updated_at": t0},
               "version": {"version_id": vid, "workflow_id": wid, "version_no": 1, "definition": parallel, "definition_hash": digest, "created_at": t0},
               "run_start": config, "accepted": {"data": {"run_id": rid, "trace_id": "a" * 32, "execution_state": "QUEUED", "status": "RUNNING", "version_id": vid}, "message": "accepted"},
               "run": run, "snapshot": snapshot, "journal": journal, "journal_batches": batches,
               "batch_acks": [{"run_id": rid, "batch_id": batches[0]["batch_id"], "first_seq": 3, "last_seq": midpoint, "duplicate": False, "terminal_committed": False},
                              {"run_id": rid, "batch_id": batches[1]["batch_id"], "first_seq": midpoint + 1, "last_seq": len(journal), "duplicate": False, "terminal_committed": True}],
               "analysis": analysis, "dataset": dataset,
               "experiment_requests": [{"dataset_id": did, "case_code": case, "parameters": parameter, "seed": 42, "warmups": 3, "repetitions": 15} for case, parameter in zip(cases, parameters)],
               "empty_cursor_page": {"data": [], "meta": {"limit": 50, "next_cursor": None, "has_more": False}},
               "errors": {str(status): {"error": {"code": code, "message": "合成错误样例", "details": {}}} for status, code in [(409, "LEASE_LOST"), (410, "CURSOR_EXPIRED"), (412, "REVISION_MISMATCH"), (422, "WORKFLOW_INVALID"), (428, "PRECONDITION_REQUIRED")]}}
    aggregate = {"snapshot_at": t1, "watermark_max_seq": 1, "stale": False, "refreshing": False}
    example["aggregate_status"] = aggregate
    example["capabilities"] = {"protocol_version": "2.0", "features": {"workflow_editor": True, "durable_queue": True, "live_graph": True, "experiments": True},
                               "limits": {"nodes": 50, "edges": 100, "spans": 500, "span_events": 2000, "journal_events": 5000, "max_parallelism": 4},
                               "scenarios": ["RESEARCH_PIPELINE", "PARALLEL_RETRIEVAL", "QUALITY_GATE"], "algorithm_version": "2.0", "experiment_protocol_version": "2.0"}
    example["overview"] = {"total_runs": 1, "running_runs": 0, "queued_runs": 0, "success_runs": 1, "failed_runs": 0,
                           "cancelled_runs": 0, "success_rate": 1, "avg_execution_duration_ms": 600, "p50_execution_duration_ms": 600,
                           "p95_execution_duration_ms": 600, "input_tokens": 0, "output_tokens": 0, "total_spans": 7,
                           "dataset_counts": {"agents": 1, "tasks": 1, "runs": 1, "spans": 7}, "recent_runs": [run], "aggregate_status": aggregate}
    example["validation"] = {"valid": True, "errors": []}
    running = copy.deepcopy(snapshot)
    running["seq"], running["projection_complete"], running["links"], running["event_count"] = midpoint, False, [], 0
    running["run"].update({"status": "RUNNING", "execution_state": "RUNNING", "ended_at": None, "execution_ended_at": None,
                           "execution_duration_ms": None, "logical_duration_ms": 0, "last_seq": midpoint, "span_count": 5, "progress": 0.2})
    cp = checkpoint(False)
    running["nodes"] = [{"node_key": key, **{k: v for k, v in value.items() if k != "result"}} for key, value in cp["node_states"].items()]
    running["spans"] = [{**spans[n], "state": "SUCCESS" if n == 3 else "RUNNING", "end_time": t0 if n == 3 else None,
                          **{key: None for key in ("input_tokens", "output_tokens", "provider", "model_name", "tool_name", "error_type", "error_message")}} for n in (1, 2, 3, 4, 5)]
    example["running_snapshot"] = running
    other_run = str(UUID(int=8000))
    example["comparison"] = {"run_ids": [rid, other_run], "version_id": vid, "time_basis": "REALTIME",
                             "summary_rows": [{"run_id": value, "execution_duration_ms": 600, "input_tokens": 0, "output_tokens": 0, "status": "SUCCESS"} for value in (rid, other_run)],
                             "node_rows": [{"node_key": value["node_key"], "per_run": [{"run_id": run_id, "state": "SUCCESS", "attempt_count": 1,
                                             "duration_ms": 300 if value["node_key"] == "search_a" else 600 if value["node_key"] == "search_b" else 0,
                                             "input_tokens": None, "output_tokens": None} for run_id in (rid, other_run)]} for value in parallel["nodes"]],
                             "deltas": {"execution_duration_ms": 0, "execution_relative_change": 0}}
    example["experiment_results"] = []
    variants = [["no_candidate", "single_run", "composite_run_start"], ["no_gin", "gin_ops", "gin_path_ops"],
                ["offset", "keyset"], ["raw", "summary", "daily_mv"], ["read_committed", "repeatable_read", "serializable"], ["blocking", "skip_locked"]]
    for index, request in enumerate(example["experiment_requests"]):
        experiment_id = eid if index == 0 else str(UUID(int=9000 + index))
        trials, samples = [], []
        for ordinal, variant in enumerate(variants[index], 1):
            trial_id = str(UUID(int=10000 + index * 10 + ordinal))
            summary = {"n": 15, "median_ms": 1, "p95_ms": 1, "iqr_ms": 0,
                       "paired_difference_ms": 0, "bootstrap_ci95_ms": [0, 0], "failed_samples": 0}
            trials.append({"trial_id": trial_id, "experiment_id": experiment_id, "ordinal": ordinal,
                           "variant": variant, "parameters": request["parameters"], "summary": summary})
            for repetition in range(18):
                samples.append({"trial_id": trial_id, "repetition": repetition, "is_warmup": repetition < 3, "measured_at": t1,
                                "metrics": {"execution_ms": 1, "client_ms": 1, "returned_rows": 1, "scanned_rows": 1,
                                            "shared_hit_blocks": 1, "shared_read_blocks": 0, "local_hit_blocks": 0, "temp_read_blocks": 0,
                                            "index_bytes": None, "insert_ms": None, "extra": {"synthetic": True}},
                                "plan": {"Plan": {"Node Type": "Seq Scan", "Relation Name": "synthetic_only", "Actual Rows": 1, "Actual Loops": 1}, "Execution Time": 1},
                                "correctness": {"passed": True, "checks": {"synthetic_fixture": True}, "result_hash": None}})
        example["experiment_results"].append({"experiment": {"experiment_id": experiment_id, "dataset_id": did, "case_code": request["case_code"],
                    "status": "SUCCESS", "phase": "EXPORTING", "progress": 1, "cancel_requested_at": None, "runner_id": "synthetic-fixture",
                    "config": request, "environment": {"synthetic": True}, "protocol_version": "2.0", "code_revision": "design-only",
                    "created_at": t0, "started_at": t0, "ended_at": t1, "error_code": None, "trial_count": len(trials), "sample_count": len(samples)},
                    "trials": trials, "samples": samples})
    write("examples.json", example)
    entries = [
        ("GET", "/capabilities", 200), ("GET", "/overview", 200),
        ("GET", "/workflows", 200), ("POST", "/workflows", 201), ("GET", "/workflows/{id}", 200), ("PATCH", "/workflows/{id}", 200),
        ("POST", "/workflows/{id}/validate", 200), ("POST", "/workflows/{id}/versions", 201), ("GET", "/workflows/{id}/versions", 200), ("GET", "/workflow-versions/{id}", 200),
        ("POST", "/tasks/{task_id}/runs", 202), ("GET", "/runs", 200), ("GET", "/runs/{run_id}", 200), ("POST", "/runs/{run_id}/cancel", 200),
        ("GET", "/runs/{run_id}/snapshot", 200), ("GET", "/runs/{run_id}/journal", 200), ("GET", "/runs/{run_id}/stream", 200), ("GET", "/runs/{run_id}/analysis", 200),
        ("POST", "/comparisons", 200), ("GET", "/search/spans", 200), ("GET", "/search/events", 200),
        ("GET", "/analytics/series", 200), ("GET", "/analytics/agents", 200), ("GET", "/analytics/aggregate-status", 200), ("POST", "/analytics/refresh", 200),
        ("GET", "/datasets", 200), ("POST", "/datasets", 201), ("GET", "/datasets/{id}", 200), ("POST", "/datasets/{id}/finalize", 200),
        ("GET", "/experiments", 200), ("POST", "/experiments", 202), ("GET", "/experiments/{id}", 200), ("POST", "/experiments/{id}/cancel", 200),
        ("GET", "/experiments/{id}/trials", 200), ("GET", "/experiments/{id}/samples", 200), ("GET", "/experiments/{id}/export", 200),
        ("GET", "/database/catalog", 200), ("GET", "/database/query-templates", 200), ("GET", "/audit", 200)]
    manifest = {"protocol_version": "2.0", "status": "design_only", "routes": []}
    for method, path, status in entries:
        item = {"method": method, "path": "/api/v2" + path, "success_status": status,
                "owner": "B", "implemented": False, "transport": "SSE" if path.endswith("/stream") else "JSON"}
        if method == "POST" and path in ("/tasks/{task_id}/runs", "/experiments"):
            item["required_headers"] = ["Idempotency-Key"]
        if method == "PATCH" or method == "POST" and path == "/workflows/{id}/versions":
            item["required_headers"] = ["If-Match"]
        manifest["routes"].append(item)
    write("http-manifest.json", manifest)


if __name__ == "__main__":
    schemas()
    artifacts()
    print("Built 4 synthetic design artifacts; no service or database changed.")
