import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from app.lab.database import configure, engine, identifier

METRICS = (
    "execution_ms",
    "client_ms",
    "returned_rows",
    "scanned_rows",
    "shared_hit_blocks",
    "shared_read_blocks",
    "local_hit_blocks",
    "temp_read_blocks",
    "index_bytes",
    "insert_ms",
)


def result_hash(result):
    # Query-result equality, separate from the missing logical-dataset hash spec.
    value = json.dumps(
        jsonable_encoder(result), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(value.encode()).hexdigest()


def query(conn, sql, parameters):
    started = time.perf_counter()
    hashed = hashlib.sha256()
    count = 0
    # Hash ordered rows in bounded batches, including the client fetch cost.
    with conn.execute(
        text(sql).execution_options(stream_results=True, yield_per=1000), parameters
    ) as result:
        for row in result.mappings():
            value = json.dumps(
                jsonable_encoder(dict(row)),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            hashed.update(value.encode("utf-8") + b"\n")
            count += 1
    elapsed = (time.perf_counter() - started) * 1000
    plan = conn.scalar(
        text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), parameters
    )[0]
    root = plan["Plan"]

    def scanned(node):
        children = node.get("Plans", [])
        if children:
            return sum(scanned(child) for child in children)
        return (
            node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0)
        ) * node.get("Actual Loops", 1)

    metrics = dict.fromkeys(METRICS)
    metrics.update(
        execution_ms=plan["Execution Time"],
        client_ms=elapsed,
        returned_rows=count,
        scanned_rows=scanned(root),
        shared_hit_blocks=root.get("Shared Hit Blocks", 0),
        shared_read_blocks=root.get("Shared Read Blocks", 0),
        local_hit_blocks=root.get("Local Hit Blocks", 0),
        temp_read_blocks=root.get("Temp Read Blocks", 0),
    )
    return (
        metrics,
        plan,
        {
            "passed": True,
            "checks": {"row_count": count},
            "result_hash": hashed.hexdigest(),
        },
    )


def insertion_probe(conn):
    """Same constrained 100-row insert in each layout, then SAVEPOINT rollback.

    This is database write overhead, explicitly not business API throughput.
    The probe preserves every benchmark row and all primary/foreign/check rules.
    """
    savepoint = conn.begin_nested()
    started = time.perf_counter()
    try:
        result = conn.execute(
            text("""WITH source AS (SELECT * FROM spans WHERE parent_span_id IS NOT NULL ORDER BY span_pk LIMIT 1)
          INSERT INTO spans(run_id,span_id,parent_span_id,agent_id,operation_type,span_name,status,start_time,end_time,
            provider,model_name,tool_name,input_tokens,output_tokens,error_type,error_message,attributes)
          SELECT s.run_id,substring(md5(gen_random_uuid()::text),1,16),s.parent_span_id,s.agent_id,s.operation_type,
            s.span_name,s.status,s.start_time,s.end_time,s.provider,s.model_name,s.tool_name,s.input_tokens,s.output_tokens,
            s.error_type,s.error_message,s.attributes FROM source s CROSS JOIN generate_series(1,100)""")
        )
        return (time.perf_counter() - started) * 1000, result.rowcount
    finally:
        savepoint.rollback()


def vacuum_after_probe(conn, dataset_id):
    # Rollback preserves logical records but leaves aborted heap/index tuples.
    # Remove them before the next paired query; account for this cost separately.
    started = time.perf_counter()
    conn.execution_options(isolation_level="AUTOCOMMIT")
    try:
        conn.execute(text(f"VACUUM (ANALYZE) {identifier(conn, dataset_id)}.spans"))
        conn.commit()
    finally:
        conn.rollback()
        conn.execution_options(isolation_level="READ COMMITTED")
    return (time.perf_counter() - started) * 1000


def queue(dataset_id, variant, claimers, control, lock_connection):
    token = uuid4()
    with lock_connection.begin():
        conn = lock_connection
        configure(conn, dataset_id)
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS lab_queue(id integer PRIMARY KEY,run_token uuid NOT NULL,done boolean NOT NULL DEFAULT false)"
            )
        )
        conn.execute(text("TRUNCATE lab_queue"))
        conn.execute(
            text(
                "INSERT INTO lab_queue(id,run_token) SELECT generate_series(1,1000),CAST(:token AS uuid)"
            ),
            {"token": token},
        )
    barrier = Barrier(claimers)
    suffix = " SKIP LOCKED" if variant == "skip_locked" else ""

    def consume(worker):
        completed, latencies = [], []
        barrier.wait(timeout=10)
        while True:
            if len(completed) % 25 == 0:
                control()
            begin = time.perf_counter()
            with engine().begin() as conn:
                configure(conn, dataset_id)
                job = conn.scalar(
                    text(
                        "SELECT id FROM lab_queue WHERE NOT done AND run_token=:token ORDER BY id FOR UPDATE"
                        + suffix
                        + " LIMIT 1"
                    ),
                    {"token": token},
                )
                if job is not None:
                    conn.execute(
                        text(
                            "UPDATE lab_queue SET done=true WHERE id=:id AND run_token=:token"
                        ),
                        {"id": job, "token": token},
                    )
            if job is None:
                break
            latencies.append((time.perf_counter() - begin) * 1000)
            completed.append(job)
            # Work is deliberately outside the transaction/row lock.
            time.sleep(0.001)
        return completed, latencies

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=claimers) as pool:
        result = list(pool.map(consume, range(claimers)))
    elapsed = (time.perf_counter() - started) * 1000
    ids = [item for completed, _ in result for item in completed]
    duplicates = len(ids) - len(set(ids))
    metrics = dict.fromkeys(METRICS)
    metrics.update(
        client_ms=elapsed,
        returned_rows=len(ids),
        extra={
            "throughput_jobs_s": len(ids) * 1000 / elapsed,
            "claim_latency_ms": [
                latency for _, latencies in result for latency in latencies
            ],
            "jobs_per_claimer": [len(completed) for completed, _ in result],
            "duplicate_completions": duplicates,
            "work_ms_per_job": 1,
            "strategy": variant,
        },
    )
    return (
        metrics,
        None,
        {
            "passed": len(ids) == 1000 and duplicates == 0,
            "checks": {"claimed": len(ids), "unique": len(set(ids))},
            "result_hash": result_hash(sorted(ids)),
        },
    )
