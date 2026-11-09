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
