import os

import pytest
from sqlalchemy import make_url, text


@pytest.fixture(scope="session")
def database():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL *_test database")
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        pytest.fail("Refusing to clear a database whose name does not end with _test")
    from app.core.database import get_engine
    from app.models.tables import tables
    from app.migrate import migrate

    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    tables.cache_clear()
    migrate()
    yield get_engine()
    get_engine().dispose()
    get_engine.cache_clear()
    tables.cache_clear()
    if old is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old


@pytest.fixture
def db(database):
    with database.begin() as conn:
        conn.execute(text("TRUNCATE span_events, spans, runs, tasks, agents CASCADE"))
    return database


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client
