"""Fixed laboratory SQL registry. Identifiers never come from request text."""

import time

from sqlalchemy import text

from app.core.errors import AppError
from app.repositories.v2 import rows

VARIANTS = {
    "INDEX_SELECTIVITY": {
        "TRACE": ["no_candidate", "single_run", "composite_run_start"],
        "ERROR": ["no_candidate", "full_status_time", "error_partial"],
    },
    "JSONB_GIN": ["no_gin", "gin_ops", "gin_path_ops"],
    "PAGINATION": ["offset", "keyset"],
    "AGGREGATION": ["raw", "summary", "daily_mv"],
    "MVCC_ISOLATION": ["read_committed", "repeatable_read", "serializable"],
    "QUEUE_CONTENTION": ["blocking", "skip_locked"],
}


def variants(case, parameters):
    value = VARIANTS[case]
    return value[parameters["query"]] if isinstance(value, dict) else value


def restore_layout(conn):
    conn.execute(text("DROP INDEX IF EXISTS lab_candidate"))
    conn.execute(text("DROP INDEX IF EXISTS lab_pagination_cursor"))
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_spans_run_start ON spans(run_id,start_time)"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_spans_error_time ON spans(start_time DESC) WHERE status='ERROR'"
        )
    )


def select_query(conn, case, p):
    """Derive bounded parameters from actual data, reporting realized selectivity."""
    total = conn.scalar(text("SELECT count(*) FROM spans"))
    if not total:
        raise AppError(422, "VALIDATION_ERROR", "Dataset has no spans")
    extra = {"dataset_spans": total}
    if case == "INDEX_SELECTIVITY" and p["query"] == "TRACE":
        candidate = rows(
            conn,
            """SELECT run_id,count(*) AS n FROM spans GROUP BY run_id
          ORDER BY abs(count(*)*1.0/:total-:target),run_id LIMIT 1""",
            total=total,
            target=p["selectivity"],
        )[0]
        extra.update(
            target_selectivity=p["selectivity"],
            actual_selectivity=candidate["n"] / total,
        )
        return (
            "SELECT span_id FROM spans WHERE run_id=:run ORDER BY start_time,span_id",
            {"run": candidate["run_id"]},
            extra,
        )
    if case == "INDEX_SELECTIVITY":
        errors = conn.scalar(text("SELECT count(*) FROM spans WHERE status='ERROR'"))
        if not errors:
            raise AppError(422, "VALIDATION_ERROR", "Dataset has no ERROR spans")
        offset = min(errors - 1, max(0, int(total * p["selectivity"]) - 1))
        cutoff = conn.scalar(
            text(
                "SELECT start_time FROM spans WHERE status='ERROR' ORDER BY start_time,span_id OFFSET :offset LIMIT 1"
            ),
            {"offset": offset},
        )
        actual = conn.scalar(
            text(
                "SELECT count(*) FROM spans WHERE status='ERROR' AND start_time<=:cutoff"
            ),
            {"cutoff": cutoff},
        )
        extra.update(
            target_selectivity=p["selectivity"], actual_selectivity=actual / total
        )
        return (
            "SELECT span_id FROM spans WHERE status='ERROR' AND start_time<=:cutoff ORDER BY start_time,span_id",
            {"cutoff": cutoff},
            extra,
        )
    if case == "JSONB_GIN":
        candidate = rows(
            conn,
            """SELECT attributes->'region' AS region,count(*) AS n FROM spans WHERE attributes ? 'region'
          GROUP BY 1 ORDER BY abs(count(*)*1.0/:total-:target),1 LIMIT 1""",
            total=total,
            target=p["selectivity"],
        )
        if not candidate:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "Dataset must contain the documented region attribute",
            )
        from app.repositories.v2 import encode

        extra.update(
            target_selectivity=p["selectivity"],
            actual_selectivity=candidate[0]["n"] / total,
            selection_rule="closest observed region frequency; target is not asserted as actual",
        )
        return (
            "SELECT span_id FROM spans WHERE attributes @> CAST(:attributes AS jsonb) ORDER BY span_id",
            {"attributes": encode({"region": candidate[0]["region"]})},
            extra,
        )
    if case == "PAGINATION":
        started = time.perf_counter()
        conn.execute(
            text("CREATE INDEX lab_pagination_cursor ON spans(start_time,span_pk)")
        )
        extra["cursor_index_build_ms"] = (time.perf_counter() - started) * 1000
        extra["cursor_index_bytes"] = conn.scalar(
            text("SELECT pg_relation_size('lab_pagination_cursor')")
        )
        extra["reachable"] = p["rank"] < total
        started = time.perf_counter()
        previous = (
            rows(
                conn,
                "SELECT start_time,span_pk FROM spans ORDER BY start_time,span_pk OFFSET :rank LIMIT 1",
                rank=max(0, p["rank"] - 1),
            )
            if p["rank"]
            else []
        )
        extra["cursor_construction_ms"] = (time.perf_counter() - started) * 1000
        extra["cursor"] = previous[0] if previous else None
        return (
            "SELECT span_pk FROM spans ORDER BY start_time,span_pk LIMIT 50 OFFSET :rank",
            {"rank": p["rank"]},
            extra,
        )
    if case == "AGGREGATION":
        end = conn.scalar(
            text("SELECT (max(started_at) AT TIME ZONE 'UTC')::date+1 FROM runs")
        )
        from datetime import timedelta

        return "", {"start": end - timedelta(days=p["window_days"]), "end": end}, extra
    raise AppError(422, "VALIDATION_ERROR", "Not a query case")


PER_RUN = """SELECT r.run_id,(r.started_at AT TIME ZONE 'UTC')::date AS day,
 count(s.span_id) AS spans,coalesce(sum(s.input_tokens) FILTER(WHERE s.operation_type='LLM'),0) AS input_tokens,
 coalesce(sum(s.output_tokens) FILTER(WHERE s.operation_type='LLM'),0) AS output_tokens,
 extract(epoch FROM r.ended_at-r.started_at)*1000 AS duration_ms
 FROM runs r LEFT JOIN spans s USING(run_id) WHERE r.status IN ('SUCCESS','FAILED','CANCELLED')
 GROUP BY r.run_id"""
AGGREGATE = """SELECT day,count(*) AS runs,sum(spans) AS spans,sum(input_tokens) AS input_tokens,
 sum(output_tokens) AS output_tokens,count(duration_ms) AS duration_count,coalesce(sum(duration_ms),0) AS duration_sum_ms
 FROM {source} WHERE day>=:start AND day<:end GROUP BY day ORDER BY day"""


def prepare_aggregation(conn):
    conn.execute(text("CREATE TABLE IF NOT EXISTS lab_summaries AS " + PER_RUN))
    conn.execute(
        text(
            "CREATE MATERIALIZED VIEW IF NOT EXISTS lab_daily AS "
            + AGGREGATE.format(source="lab_summaries").replace(
                "WHERE day>=:start AND day<:end", ""
            )
        )
    )
    started = time.perf_counter()
    conn.execute(text("REFRESH MATERIALIZED VIEW lab_daily"))
    return {
        "refresh_ms": (time.perf_counter() - started) * 1000,
        "summary_bytes": conn.scalar(
            text("SELECT pg_total_relation_size('lab_summaries')")
        ),
        "mv_bytes": conn.scalar(text("SELECT pg_total_relation_size('lab_daily')")),
    }


def layout(conn, case, variant, sql, parameters, extra):
    before = time.perf_counter()
    if case in {"INDEX_SELECTIVITY", "JSONB_GIN"}:
        # Other primary/unique/foreign-key supporting indexes remain in place.
        names = ["lab_candidate"]
        if case == "INDEX_SELECTIVITY":
            names.append(
                "idx_spans_run_start"
                if variant in {"single_run", "composite_run_start"}
                or "run" in parameters
                else "idx_spans_error_time"
            )
        for name in names:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        definitions = {
            "single_run": "ON spans(run_id)",
            "composite_run_start": "ON spans(run_id,start_time)",
            "full_status_time": "ON spans(status,start_time)",
            "error_partial": "ON spans(start_time) WHERE status='ERROR'",
            "gin_ops": "ON spans USING gin(attributes jsonb_ops)",
            "gin_path_ops": "ON spans USING gin(attributes jsonb_path_ops)",
        }
        if variant in definitions:
            conn.execute(text("CREATE INDEX lab_candidate " + definitions[variant]))
    elif case == "PAGINATION" and variant == "keyset":
        if extra["cursor"]:
            sql = "SELECT span_pk FROM spans WHERE (start_time,span_pk)>(:time,:pk) ORDER BY start_time,span_pk LIMIT 50"
            parameters = {
                "time": extra["cursor"]["start_time"],
                "pk": extra["cursor"]["span_pk"],
            }
        elif parameters["rank"]:
            sql, parameters = "SELECT span_pk FROM spans WHERE false", {}
        else:
            sql, parameters = (
                "SELECT span_pk FROM spans ORDER BY start_time,span_pk LIMIT 50",
                {},
            )
    elif case == "AGGREGATION":
        if variant == "raw":
            sql = AGGREGATE.format(source="(" + PER_RUN + ") AS per_run")
        elif variant == "summary":
            sql = AGGREGATE.format(source="lab_summaries")
        else:
            sql = "SELECT * FROM lab_daily WHERE day>=:start AND day<:end ORDER BY day"
    build_ms = (time.perf_counter() - before) * 1000
    before = time.perf_counter()
    conn.execute(text("ANALYZE spans"))
    analyze_ms = (time.perf_counter() - before) * 1000
    index_bytes = conn.scalar(
        text("SELECT coalesce(pg_relation_size(to_regclass('lab_candidate')),0)")
    )
    return (
        sql,
        parameters,
        {"build_ms": build_ms, "analyze_ms": analyze_ms, "index_bytes": index_bytes},
    )
