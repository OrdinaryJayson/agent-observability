"""Owner-only setup for an empty, physically separate experiment database."""

import hashlib

from sqlalchemy import text

from app.core.config import ROOT
from app.core.errors import AppError
from app.lab.database import LAB_LOCK, check_database, engine


def bootstrap(conn):
    check_database(conn)
    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LAB_LOCK})
    source = (ROOT / "database/migrations/001_init.sql").read_text(encoding="utf-8")
    checksum = hashlib.sha256(source.encode()).hexdigest()
    stamp = conn.scalar(text("SELECT to_regclass('public.lab_template_migrations')"))
    if stamp is None:
        if conn.scalar(text("SELECT to_regclass('public.spans')")) is not None:
            raise AppError(
                409,
                "CONFLICT",
                "Unmanaged laboratory templates already exist; owner review required",
            )
        conn.execute(text("SET LOCAL search_path TO public,pg_catalog"))
        conn.connection.driver_connection.execute(source, prepare=False)
        conn.execute(
            text(
                "CREATE TABLE public.lab_template_migrations(singleton boolean PRIMARY KEY CHECK(singleton),checksum char(64) NOT NULL)"
            )
        )
        conn.execute(
            text("INSERT INTO public.lab_template_migrations VALUES(true,:hash)"),
            {"hash": checksum},
        )
    elif (
        conn.scalar(text("SELECT checksum FROM public.lab_template_migrations"))
        != checksum
    ):
        raise AppError(
            409, "CONFLICT", "Laboratory template checksum differs from frozen 001"
        )
    conn.execute(text((ROOT / "database/lab_roles.sql").read_text(encoding="utf-8")))


def main():
    with engine().begin() as conn:
        bootstrap(conn)
    engine().dispose()
    print("Isolated laboratory templates and role permissions are ready")


if __name__ == "__main__":
    main()
