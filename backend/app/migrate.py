"""Run from backend: python -m app.migrate. Each migration and its record are atomic."""

import hashlib

from sqlalchemy import text

from app.core.config import ROOT
from app.core.database import get_engine


def migrate() -> None:
    with get_engine().begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(90624117)"))
        conn.execute(
            text("""CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY, checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        )
        applied = dict(
            conn.execute(text("SELECT filename, checksum FROM schema_migrations")).all()
        )
        for path in sorted((ROOT / "database/migrations").glob("*.sql")):
            content = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(content.encode()).hexdigest()
            if path.name in applied:
                if applied[path.name] != checksum:
                    raise RuntimeError(f"Applied migration changed: {path.name}")
                continue
            conn.connection.driver_connection.execute(content, prepare=False)
            conn.execute(
                text(
                    "INSERT INTO schema_migrations(filename, checksum) VALUES (:f, :c)"
                ),
                {"f": path.name, "c": checksum},
            )
            print(f"Applied {path.name}")


if __name__ == "__main__":
    migrate()
