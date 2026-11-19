"""Controlled two-transaction primitives for C's barrier schedule driver.

There is deliberately no API accepting SQL, a table name, or an isolation string
outside the registry. Callers own barriers and must close every transaction.
"""

from sqlalchemy import text

from app.lab.database import configure, engine

ISOLATION = {
    "read_committed": "READ COMMITTED",
    "repeatable_read": "REPEATABLE READ",
    "serializable": "SERIALIZABLE",
}


def prepare(conn):
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS lab_duty(id integer PRIMARY KEY,active boolean NOT NULL)"
        )
    )
    conn.execute(
        text(
            "INSERT INTO lab_duty VALUES(1,true),(2,true) ON CONFLICT(id) DO UPDATE SET active=true"
        )
    )


class DutyTransaction:
    def __init__(self, dataset_id, variant):
        self.conn = (
            engine().connect().execution_options(isolation_level=ISOLATION[variant])
        )
        self.transaction = self.conn.begin()
        try:
            configure(self.conn, dataset_id)
        except BaseException:
            self.close()
            raise

    def active_count(self):
        return self.conn.scalar(text("SELECT count(*) FROM lab_duty WHERE active"))

    def set_inactive(self, row_id):
        if row_id not in {1, 2}:
            raise ValueError("Only the two registered duty records are permitted")
        self.conn.execute(
            text("UPDATE lab_duty SET active=false WHERE id=:id"), {"id": row_id}
        )

    def commit(self):
        self.transaction.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
