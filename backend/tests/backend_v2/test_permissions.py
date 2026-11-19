from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_application_role_dml_without_ddl_or_history_mutation(db):
    script = Path(__file__).resolve().parents[3] / "database/roles.sql"
    with db.begin() as conn:
        conn.execute(text(script.read_text(encoding="utf-8")))
    with db.begin() as conn:
        conn.execute(text("SET LOCAL ROLE observability_app"))
        conn.execute(text("INSERT INTO tasks(title) VALUES('least privilege')"))
        assert conn.scalar(text("SELECT count(*) FROM tasks")) == 1
        conn.execute(text("SELECT public.v2_refresh_metrics()"))
    for statement in (
        "CREATE TABLE public.must_not_exist(id int)",
        "DELETE FROM audit_log",
        "UPDATE workflow_versions SET version_no=9",
        "TRUNCATE runs CASCADE",
    ):
        with pytest.raises(DBAPIError) as error:
            with db.begin() as conn:
                conn.execute(text("SET LOCAL ROLE observability_app"))
                conn.execute(text(statement))
        assert error.value.orig.sqlstate == "42501"
    with db.connect() as conn:
        assert not conn.scalar(
            text(
                "SELECT has_database_privilege('observability_lab',current_database(),'CONNECT')"
            )
        )


def test_terminal_commit_with_application_privileges(running, db, monkeypatch):
    from sqlalchemy import create_engine
    from app.core.config import database_url
    from app.services import v2_journal

    with db.begin() as conn:
        conn.execute(
            text(
                (Path(__file__).resolve().parents[3] / "database/roles.sql").read_text(
                    encoding="utf-8"
                )
            )
        )
    limited = create_engine(
        database_url(),
        pool_size=1,
        max_overflow=0,
        connect_args={"options": "-c role=observability_app -c timezone=UTC"},
    )
    monkeypatch.setattr(v2_journal, "get_engine", lambda: limited)
    try:
        with limited.connect() as conn:
            assert conn.scalar(text("SELECT current_user")) == "observability_app"
        _, batches, _ = running
        for batch in batches:
            result = v2_journal.commit("worker-a", batch)
        assert result["terminal_committed"]
        with limited.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM run_summaries")) == 1
    finally:
        limited.dispose()
