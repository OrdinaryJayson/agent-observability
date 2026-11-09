"""Reflect migrated SQL as the single source of truth; never create tables at startup."""

from functools import lru_cache

from sqlalchemy import MetaData, Table

from app.core.database import get_engine


@lru_cache
def tables() -> dict[str, Table]:
    metadata = MetaData()
    metadata.reflect(
        get_engine(), only=["agents", "tasks", "runs", "spans", "span_events"]
    )
    return dict(metadata.tables)
