from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import get_engine, read_snapshot
from app.core.errors import AppError
from app.repositories.v2 import audit, one, rows

AGGREGATE_SQL = """SELECT (s.run_started_at AT TIME ZONE 'UTC')::date AS day,s.execution_mode,e.version_id,
 count(*) FILTER(WHERE final_status='SUCCESS') AS success_runs,
 count(*) FILTER(WHERE final_status='FAILED') AS failed_runs,
 count(*) FILTER(WHERE final_status='CANCELLED') AS cancelled_runs,
 count(s.execution_duration_ms) AS duration_count,coalesce(sum(s.execution_duration_ms),0) AS duration_sum_ms,
 sum(input_tokens) AS input_tokens,sum(output_tokens) AS output_tokens,sum(span_count) AS span_count,
 max(summary_seq) AS watermark_max_seq FROM run_summaries s LEFT JOIN run_executions e USING(run_id)
 GROUP BY 1,2,3"""
METRICS = "day,execution_mode,version_id,success_runs,failed_runs,cancelled_runs,duration_count,duration_sum_ms,input_tokens,output_tokens,span_count,watermark_max_seq"


def aggregate_status(conn):
    base = one(
        conn,
        "SELECT max(snapshot_at) AS snapshot_at,coalesce(max(watermark_max_seq),0) AS watermark_max_seq FROM mv_daily_metrics",
    )
    base["stale"] = conn.execute(
        text(f"""WITH actual AS ({AGGREGATE_SQL}), saved AS (SELECT {METRICS} FROM mv_daily_metrics)
      SELECT EXISTS((SELECT * FROM actual EXCEPT SELECT * FROM saved) UNION ALL
                    (SELECT * FROM saved EXCEPT SELECT * FROM actual))""")
    ).scalar_one()
    base["refreshing"] = conn.execute(
        text("""SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory'
      AND classid=0 AND objid=90624118 AND granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database()))""")
    ).scalar_one()
    return base


def refresh():
    with get_engine().begin() as conn:
        if not conn.execute(
            text("SELECT pg_try_advisory_xact_lock(90624118)")
        ).scalar_one():
            raise AppError(409, "CONFLICT", "Aggregate refresh is in progress")
        try:
            conn.execute(text("SET LOCAL statement_timeout='10s'"))
            conn.execute(text("SELECT public.v2_refresh_metrics()"))
            audit(conn, "analytics.refreshed", "aggregate", None)
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "57014":
                raise AppError(
                    504, "AGGREGATE_REFRESH_TIMEOUT", "Aggregate refresh timed out"
                ) from exc
            raise
    with read_snapshot() as conn:
        return aggregate_status(conn)


def window(query, column="r.started_at"):
    conditions = ["coalesce(e.config->>'mode','LEGACY')=:mode"]
    parameters = {"mode": query.mode}
    for key, operator in (("from_time", ">="), ("to_time", "<")):
        value = getattr(query, key)
        if value is not None:
            conditions.append(f"{column}{operator}:{key}")
            parameters[key] = value
    return " AND ".join(conditions), parameters


def overview(conn, query):
    condition, parameters = window(query)
    result = one(
        conn,
        f"""SELECT count(*) AS total_runs,count(*) FILTER(WHERE r.status='RUNNING') AS running_runs,
      count(*) FILTER(WHERE e.execution_state='QUEUED') AS queued_runs,
      count(*) FILTER(WHERE r.status='SUCCESS') AS success_runs,count(*) FILTER(WHERE r.status='FAILED') AS failed_runs,
      count(*) FILTER(WHERE r.status='CANCELLED') AS cancelled_runs,
      avg(s.execution_duration_ms) AS avg_execution_duration_ms,
      percentile_cont(0.5) WITHIN GROUP(ORDER BY s.execution_duration_ms) AS p50_execution_duration_ms,
      percentile_cont(0.95) WITHIN GROUP(ORDER BY s.execution_duration_ms) AS p95_execution_duration_ms,
      coalesce(sum(f.input_tokens),0) AS input_tokens,coalesce(sum(f.output_tokens),0) AS output_tokens,
      coalesce(sum(f.span_count),0) AS total_spans
      FROM runs r LEFT JOIN run_executions e USING(run_id) LEFT JOIN run_summaries s USING(run_id)
      JOIN v_run_facts f ON f.run_id=r.run_id WHERE {condition}""",
        **parameters,
    )
    terminal = result["success_runs"] + result["failed_runs"]
    result["success_rate"] = result["success_runs"] / terminal if terminal else None
    result["dataset_counts"] = {
        row["purpose"]: row["count"]
        for row in rows(
            conn, "SELECT purpose,count(*) FROM dataset_manifests GROUP BY purpose"
        )
    }
    from app.services.v2_queries import run_view

    recent = rows(
        conn,
        f"SELECT r.run_id FROM runs r LEFT JOIN run_executions e USING(run_id) WHERE {condition} ORDER BY r.created_at DESC,r.run_id DESC LIMIT 10",
        **parameters,
    )
    result["recent_runs"] = [run_view(conn, row["run_id"]) for row in recent]
    result["aggregate_status"] = aggregate_status(conn)
    return result
