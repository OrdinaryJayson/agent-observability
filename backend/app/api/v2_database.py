from fastapi import APIRouter, Depends

from app.api.query import validate_query_names
from app.api.v2 import envelope
from app.core.database import read_snapshot
from app.repositories.v2 import rows

router = APIRouter(
    prefix="/api/v2/database", dependencies=[Depends(validate_query_names)]
)
TABLES = (
    "agents",
    "tasks",
    "runs",
    "spans",
    "span_events",
    "workflows",
    "workflow_versions",
    "run_executions",
    "run_journal",
    "span_links",
    "run_summaries",
    "analysis_reports",
    "request_keys",
    "dataset_manifests",
    "experiment_runs",
    "experiment_trials",
    "experiment_samples",
    "audit_log",
)
TEMPLATES = [
    {
        "code": "TRACE",
        "sql": "SELECT * FROM spans WHERE run_id=:run_id ORDER BY start_time,span_id",
        "parameters": {"run_id": "UUID"},
        "index_names": ["idx_spans_run_start"],
        "description": "Persisted trace; the run/span unique key is also a candidate access path.",
    },
    {
        "code": "ATTRIBUTES",
        "sql": "SELECT * FROM spans WHERE attributes @> CAST(:attributes AS jsonb)",
        "parameters": {"attributes": "JSON object <= 2 KiB"},
        "index_names": ["spans_attributes"],
        "description": "Containment search only; high selectivity may favor a sequential scan.",
    },
    {
        "code": "ERROR_TEXT",
        "sql": "SELECT * FROM spans WHERE to_tsvector('simple',coalesce(error_message,'')) @@ plainto_tsquery('simple',:q)",
        "parameters": {"q": "text <= 200 characters"},
        "index_names": ["spans_error_search"],
        "description": "Simple full-text configuration; no claim of Chinese word segmentation.",
    },
    {
        "code": "JOURNAL",
        "sql": "SELECT * FROM run_journal WHERE run_id=:run_id AND seq>:after_seq ORDER BY seq LIMIT :limit",
        "parameters": {
            "run_id": "UUID",
            "after_seq": "integer >= 0",
            "limit": "1..100",
        },
        "index_names": ["run_journal_pkey"],
        "description": "Durable replay ordered by per-run sequence.",
    },
]


@router.get("/query-templates")
def query_templates():
    return envelope(TEMPLATES)


@router.get("/catalog")
def catalog():
    with read_snapshot() as conn:
        result = []
        for name in TABLES:
            columns = rows(
                conn,
                """SELECT column_name AS name,data_type,is_nullable,column_default
              FROM information_schema.columns WHERE table_schema='public' AND table_name=:name ORDER BY ordinal_position""",
                name=name,
            )
            constraints = rows(
                conn,
                """SELECT c.conname AS name,pg_get_constraintdef(c.oid) AS definition
              FROM pg_constraint c JOIN pg_class t ON c.conrelid=t.oid JOIN pg_namespace n ON t.relnamespace=n.oid
              WHERE n.nspname='public' AND t.relname=:name ORDER BY c.conname""",
                name=name,
            )
            indexes = rows(
                conn,
                """SELECT indexname AS name,indexdef AS definition,
              pg_relation_size(format('%I.%I',schemaname,indexname)::regclass) AS size_bytes
              FROM pg_indexes WHERE schemaname='public' AND tablename=:name ORDER BY indexname""",
                name=name,
            )
            size = rows(
                conn,
                "SELECT pg_total_relation_size(format('public.%I',CAST(:name AS text))::regclass) AS size",
                name=name,
            )[0]["size"]
            result.append(
                {
                    "name": name,
                    "columns": columns,
                    "constraints": constraints,
                    "indexes": indexes,
                    "size_bytes": size,
                }
            )
        views = rows(
            conn,
            """SELECT c.relname AS name,pg_get_viewdef(c.oid,true) AS definition
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
          AND c.relname IN ('v_run_facts','mv_daily_metrics') AND c.relkind IN ('v','m') ORDER BY name""",
        )
        return envelope({"tables": result, "views": views})
