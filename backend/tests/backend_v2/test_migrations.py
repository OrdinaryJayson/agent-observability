import hashlib
import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.pool import NullPool

from app.core.config import ROOT, database_url


def test_v1_database_upgrade_preserves_rows_and_repeats(db):
    """Own, randomly named disposable database; never touches existing dev data."""
    name = "b_v2_upgrade_" + uuid4().hex + "_test"
    url = make_url(database_url()).set(database=name)
    admin = create_engine(
        url.set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    created = False
    legacy = None
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
            created = True
        legacy = create_engine(url, poolclass=NullPool)
        source = (ROOT / "database/migrations/001_init.sql").read_text(encoding="utf-8")
        checksum = hashlib.sha256(source.encode()).hexdigest()
        with legacy.begin() as conn:
            conn.connection.driver_connection.execute(source, prepare=False)
            conn.execute(
                text(
                    "CREATE TABLE schema_migrations(filename text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz DEFAULT now())"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO schema_migrations(filename,checksum) VALUES('001_init.sql',:checksum)"
                ),
                {"checksum": checksum},
            )
            task = conn.scalar(
                text("INSERT INTO tasks(title) VALUES('old v1 row') RETURNING task_id")
            )
            run = conn.scalar(
                text(
                    "INSERT INTO runs(task_id,trace_id,source_type,status,ended_at) VALUES(:task,:trace,'SIMULATED','SUCCESS',now()) RETURNING run_id"
                ),
                {"task": task, "trace": uuid4().hex},
            )
            conn.execute(
                text("""INSERT INTO spans(run_id,span_id,parent_span_id,operation_type,span_name,status,start_time,end_time)
              VALUES(:run,'0000000000000001',NULL,'WORKFLOW','Old root','SUCCESS',now(),now())"""),
                {"run": run},
            )
            before = conn.scalar(
                text(
                    "SELECT md5(jsonb_agg(to_jsonb(r) ORDER BY run_id)::text) FROM runs r"
                )
            )
        env = {
            **os.environ,
            "DATABASE_URL": url.render_as_string(hide_password=False),
            "PYTHONUTF8": "1",
        }
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, "-m", "app.migrate"],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert result.returncode == 0, result.stderr
        with legacy.connect() as conn:
            assert (
                conn.scalar(
                    text(
                        "SELECT md5(jsonb_agg(to_jsonb(r) ORDER BY run_id)::text) FROM runs r"
                    )
                )
                == before
            )
            assert (
                conn.scalar(
                    text(
                        "SELECT checksum FROM schema_migrations WHERE filename='001_init.sql'"
                    )
                )
                == checksum
            )
            assert conn.scalar(text("SELECT count(*) FROM schema_migrations")) == len(
                list((ROOT / "database/migrations").glob("*.sql"))
            )
            assert conn.scalar(text("SELECT span_count FROM run_summaries")) == 1
            assert (
                conn.scalar(text("SELECT execution_mode FROM run_summaries"))
                == "LEGACY"
            )
    finally:
        if legacy is not None:
            legacy.dispose()
        if created:
            # name is generated above and only this invocation's database is removed.
            assert name.startswith("b_v2_upgrade_") and name.endswith("_test")
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
