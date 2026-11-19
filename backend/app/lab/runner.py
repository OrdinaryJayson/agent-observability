import os
import platform
import random
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import get_engine
from app.core.errors import AppError
from app.lab import measure, queries
from app.lab.database import configure
from app.lab.statistics import summarize
from app.repositories.v2 import encode, rows
from app.services import v2_lab


def memory_bytes():
    try:
        if os.name != "nt":
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                (name, ctypes.c_uint64)
                for name in (
                    "physical",
                    "available",
                    "pagefile",
                    "available_pagefile",
                    "virtual",
                    "available_virtual",
                    "extended",
                )
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        return (
            status.physical
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            else "unknown"
        )
    except (OSError, AttributeError, ValueError):
        return "unknown"


def environment(conn):
    return {
        "os": platform.platform(),
        "cpu": platform.processor() or "unknown",
        "logical_cpu_count": os.cpu_count(),
        "memory_bytes": memory_bytes(),
        "disk_type": "unknown",
        "postgresql_version": conn.scalar(text("SELECT version()")),
        "shared_buffers": conn.scalar(text("SHOW shared_buffers")),
        "work_mem": conn.scalar(text("SHOW work_mem")),
        "connection_count": conn.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()"
            )
        ),
        "cache_conditions": "warm-cache; no OS cache eviction",
        "measurement": "client timing and separately instrumented EXPLAIN ANALYZE",
        "isolation": "REPEATABLE READ per query sample",
        "database_alias": "dedicated-lab",
        "tail_caveat": "15 repetitions give an unstable tail estimate",
    }


def persist_sample(trial_id, repetition, warmup, metrics, plan, correctness):
    with get_engine().begin() as conn:
        conn.execute(
            text("""INSERT INTO experiment_samples(trial_id,repetition,is_warmup,measured_at,metrics,plan,correctness)
          VALUES(:trial,:rep,:warmup,:at,CAST(:metrics AS jsonb),CAST(:plan AS jsonb),CAST(:correct AS jsonb))"""),
            {
                "trial": trial_id,
                "rep": repetition,
                "warmup": warmup,
                "at": datetime.now(timezone.utc),
                "metrics": encode(metrics),
                "plan": encode(plan) if plan is not None else None,
                "correct": encode(correctness),
            },
        )


def publish_summaries(experiment):
    with get_engine().begin() as conn:
        trials = rows(
            conn,
            "SELECT trial_id FROM experiment_trials WHERE experiment_id=:id ORDER BY ordinal",
            id=experiment["experiment_id"],
        )
        samples = {
            t["trial_id"]: rows(
                conn,
                "SELECT * FROM experiment_samples WHERE trial_id=:id ORDER BY repetition",
                id=t["trial_id"],
            )
            for t in trials
        }
        if not trials:
            return
        baseline = samples[trials[0]["trial_id"]]
        for trial in trials:
            summary = summarize(
                samples[trial["trial_id"]], baseline, experiment["config"]["seed"]
            )
            conn.execute(
                text(
                    "UPDATE experiment_trials SET summary=CAST(:summary AS jsonb) WHERE trial_id=:id"
                ),
                {"id": trial["trial_id"], "summary": encode(summary)},
            )


def run(experiment, lock_connection):
    case = experiment["case_code"]
    if case == "MVCC_ISOLATION":
        raise AppError(
            409,
            "FEATURE_NOT_AVAILABLE",
            "C barrier driver is not yet integrated; controlled transactions are available in app.lab.transactions",
        )
    config = experiment["config"]
    dataset_id, experiment_id = experiment["dataset_id"], experiment["experiment_id"]

    def control():
        v2_lab.control(experiment_id)

    control()
    with lock_connection.begin():
        conn = lock_connection
        configure(conn, dataset_id)
        if not conn.scalar(text("SELECT to_regclass('spans') IS NOT NULL")):
            raise AppError(409, "CONFLICT", "Verified dataset layout is absent")
        queries.restore_layout(conn)
        env = environment(conn)
        if case != "QUEUE_CONTENTION":
            sql, parameters, extra = queries.select_query(
                conn, case, config["parameters"]
            )
            if case == "AGGREGATION":
                extra.update(queries.prepare_aggregation(conn))
        else:
            sql, parameters, extra = "", {}, {}
        env["table_bytes"] = conn.scalar(text("SELECT pg_total_relation_size('spans')"))
        env["statistics_at"] = str(
            conn.scalar(
                text(
                    "SELECT last_analyze FROM pg_stat_user_tables WHERE relid='spans'::regclass"
                )
            )
        )
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE experiment_runs SET environment=CAST(:env AS jsonb) WHERE experiment_id=:id"
            ),
            {"id": experiment_id, "env": encode(env)},
        )
    variants = queries.variants(case, config["parameters"])
    trials = {}
    empty_summary = summarize([], [], config["seed"])
    with get_engine().begin() as conn:
        for ordinal, variant in enumerate(variants, 1):
            trial_id = uuid4()
            trials[variant] = trial_id
            conn.execute(
                text("""INSERT INTO experiment_trials(trial_id,experiment_id,ordinal,variant,parameters,summary)
              VALUES(:trial,:id,:ordinal,:variant,CAST(:parameters AS jsonb),CAST(:summary AS jsonb))"""),
                {
                    "trial": trial_id,
                    "id": experiment_id,
                    "ordinal": ordinal,
                    "variant": variant,
                    "parameters": encode({**config["parameters"], "observed": extra}),
                    "summary": encode(empty_summary),
                },
            )
    rng = random.Random(config["seed"])
    reference_hash = None
    total = (config["warmups"] + config["repetitions"]) * len(variants)
    completed = 0
    for repetition in range(config["warmups"] + config["repetitions"]):
        warmup = repetition < config["warmups"]
        order = variants.copy()
        rng.shuffle(order)
        v2_lab.phase(
            experiment_id, "WARMUP" if warmup else "MEASURING", completed / total
        )
        for variant in order:
            control()
            # Keep the lock session alive and fail closed if ownership vanished.
            lock_connection.execute(text("SELECT 1"))
            lock_connection.commit()
            if case == "QUEUE_CONTENTION":
                metrics, plan, correct = measure.queue(
                    dataset_id,
                    variant,
                    config["parameters"]["claimers"],
                    control,
                    lock_connection,
                )
            elif case == "PAGINATION" and not extra["reachable"]:
                metrics, plan = dict.fromkeys(measure.METRICS), None
                metrics["extra"] = {
                    "not_applicable": True,
                    "reason": "rank outside the frozen dataset",
                }
                correct = {
                    "passed": True,
                    "checks": {"reachable": False},
                    "result_hash": None,
                }
            else:
                # Layout changes are on the dedicated schema and commit before timing.
                with lock_connection.begin():
                    conn = lock_connection
                    configure(conn, dataset_id)
                    statement, args, preparation = queries.layout(
                        conn, case, variant, sql, parameters, extra
                    )
                lock_connection.execution_options(isolation_level="REPEATABLE READ")
                try:
                    with lock_connection.begin():
                        configure(lock_connection, dataset_id)
                        metrics, plan, correct = measure.query(
                            lock_connection, statement, args
                        )
                        if case in {"INDEX_SELECTIVITY", "JSONB_GIN"}:
                            metrics["insert_ms"], preparation["insert_probe_rows"] = (
                                measure.insertion_probe(lock_connection)
                            )
                            preparation["insert_probe_committed"] = False
                except DBAPIError as exc:
                    metrics = dict.fromkeys(measure.METRICS)
                    state = getattr(exc.orig, "sqlstate", None)
                    metrics["extra"] = {
                        "sqlstate": state,
                        "error_code": "EXPERIMENT_TIMEOUT"
                        if state in {"57014", "55P03"}
                        else "EXPERIMENT_DATABASE_ERROR",
                    }
                    persist_sample(
                        trials[variant],
                        repetition,
                        warmup,
                        metrics,
                        None,
                        {
                            "passed": False,
                            "checks": {"sqlstate": state},
                            "result_hash": None,
                        },
                    )
                    raise
                lock_connection.execution_options(isolation_level="READ COMMITTED")
                if case in {"INDEX_SELECTIVITY", "JSONB_GIN"}:
                    preparation["post_probe_vacuum_ms"] = measure.vacuum_after_probe(
                        lock_connection, dataset_id
                    )
                metrics.update(
                    index_bytes=preparation["index_bytes"],
                    extra={
                        **preparation,
                        "cache_conditions": "warm-cache",
                        "order_in_pair": order.index(variant),
                        "client_timing_includes": "fetch, JSON encoding and SHA256; EXPLAIN execution_ms is separate",
                    },
                )
            if correct["result_hash"] is not None:
                if reference_hash is None:
                    reference_hash = correct["result_hash"]
                correct["checks"]["same_result_as_reference"] = (
                    correct["result_hash"] == reference_hash
                )
                correct["passed"] &= correct["result_hash"] == reference_hash
            persist_sample(trials[variant], repetition, warmup, metrics, plan, correct)
            completed += 1
            if not correct["passed"]:
                raise AppError(
                    422,
                    "EXPERIMENT_CORRECTNESS_FAILED",
                    "Variant result differs from its paired reference",
                )
    v2_lab.phase(experiment_id, "VERIFYING", completed / total)
    publish_summaries(experiment)
    v2_lab.phase(experiment_id, "EXPORTING", 1)
    control()
