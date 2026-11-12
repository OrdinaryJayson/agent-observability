from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine

from app.core.config import database_url


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        database_url(),
        pool_pre_ping=True,
        connect_args={"options": "-c timezone=UTC", "connect_timeout": 5},
    )


@contextmanager
def read_snapshot():
    """Keep counts, page rows and related aggregates in one database snapshot."""
    with (
        get_engine()
        .connect()
        .execution_options(isolation_level="REPEATABLE READ") as conn
    ):
        yield conn
