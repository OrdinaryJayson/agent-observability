import os
from functools import lru_cache
from uuid import UUID

from sqlalchemy import create_engine, make_url, text

from app.core.config import ROOT, database_url
from app.core.errors import AppError

LAB_LOCK = 90624119


def configured_url():
    value = os.getenv("EXPERIMENT_DATABASE_URL")
    if os.getenv("EXPERIMENT_ENABLED", "false").lower() != "true" or not value:
        raise AppError(
            409, "EXPERIMENT_DISABLED", "Dedicated experiment service is disabled"
        )
    url = make_url(value)
    if (
        url.get_backend_name() != "postgresql"
        or not (url.database or "").endswith(("_lab", "_test"))
        or url.database == make_url(database_url()).database
    ):
        raise AppError(
            409,
            "EXPERIMENT_DISABLED",
            "A physically separate experiment database is required",
        )
    return url


@lru_cache(maxsize=1)
def _engine(url):
    # One session mutex plus up to eight registered queue claimers.
    return create_engine(
        url,
        pool_size=9,
        max_overflow=0,
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={
            "connect_timeout": 5,
            "application_name": "observability-v2-lab",
            "options": "-c timezone=UTC -c statement_timeout=30000 -c lock_timeout=3000",
        },
    )


def engine():
    return _engine(configured_url())


def check_database(conn):
    actual = conn.scalar(text("SELECT current_database()"))
    if (
        actual != configured_url().database
        or actual == make_url(database_url()).database
    ):
        raise AppError(
            409, "EXPERIMENT_DISABLED", "Experiment database identity mismatch"
        )


def schema_name(dataset_id):
    return "lab_" + UUID(str(dataset_id)).hex


def identifier(conn, dataset_id):
    return conn.dialect.identifier_preparer.quote_identifier(schema_name(dataset_id))


def configure(conn, dataset_id):
    check_database(conn)
    conn.execute(text("SET LOCAL statement_timeout='30s'"))
    conn.execute(text("SET LOCAL lock_timeout='3s'"))
    conn.execute(
        text(f"SET LOCAL search_path TO {identifier(conn, dataset_id)},pg_catalog")
    )


def create_layout(conn, dataset_id):
    """Internal loader primitive: full v1 constraints, no business DDL."""
    configure(conn, dataset_id)
    conn.execute(text(f"CREATE SCHEMA {identifier(conn, dataset_id)}"))
    source = (ROOT / "database/migrations/001_init.sql").read_text(encoding="utf-8")
    conn.connection.driver_connection.execute(source, prepare=False)


def cleanup(dataset_id, *, confirm=False):
    """Dry-run by default; explicit exact dataset confirmation, no public DDL."""
    name = schema_name(dataset_id)
    with engine().connect() as conn:
        check_database(conn)
        if not conn.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": LAB_LOCK}
        ):
            raise AppError(409, "CONFLICT", "Experiment database is busy")
        try:
            exists = conn.scalar(
                text("SELECT EXISTS(SELECT FROM pg_namespace WHERE nspname=:name)"),
                {"name": name},
            )
            if confirm and exists:
                conn.execute(
                    text(f"DROP SCHEMA {identifier(conn, dataset_id)} CASCADE")
                )
                conn.commit()
            return {
                "schema": name,
                "exists": exists,
                "deleted": bool(confirm and exists),
            }
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LAB_LOCK})
            conn.commit()
