"""Small SQL helpers; caller owns transaction boundaries and lock ordering."""

import json
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from app.core.errors import not_found


def encode(value):
    return json.dumps(jsonable_encoder(value), ensure_ascii=False, allow_nan=False)


def rows(conn, sql, **parameters):
    return [dict(row) for row in conn.execute(text(sql), parameters).mappings()]


def one(conn, sql, **parameters):
    result = rows(conn, sql, **parameters)
    if not result:
        raise not_found()
    return result[0]


def audit(conn, action, kind, resource_id, details=None, actor="LOCAL_OPERATOR"):
    conn.execute(
        text("""INSERT INTO audit_log(action,resource_type,resource_id,actor,request_id,details)
        VALUES(:action,:kind,:id,:actor,:request,CAST(:details AS jsonb))"""),
        {
            "action": action,
            "kind": kind,
            "id": resource_id,
            "actor": actor,
            "request": uuid4(),
            "details": encode(details or {}),
        },
    )


def system_event(conn, run_id, kind, payload, epoch, batch_id=None, batch_hash=None):
    from app.contracts.v2 import digest

    seq = conn.execute(
        text(
            "UPDATE run_executions SET last_seq=last_seq+1 WHERE run_id=:id RETURNING last_seq"
        ),
        {"id": run_id},
    ).scalar_one()
    conn.execute(
        text("""UPDATE run_executions SET checkpoint=jsonb_set(checkpoint,'{journal_seq}',to_jsonb(CAST(:seq AS bigint)))
      WHERE run_id=:id AND checkpoint<>'{}'::jsonb"""),
        {"id": run_id, "seq": seq},
    )
    if kind == "run.finished":
        payload = {**payload, "final_seq": seq}
    conn.execute(
        text("""INSERT INTO run_journal(run_id,seq,batch_id,batch_hash,producer_event_id,kind,payload,payload_hash,lease_epoch,occurred_at)
      VALUES(:id,:seq,:batch,:hash,:event,:kind,CAST(:payload AS jsonb),:payload_hash,:epoch,clock_timestamp())"""),
        {
            "id": run_id,
            "seq": seq,
            "batch": batch_id or uuid4(),
            "hash": batch_hash or digest(payload),
            "event": uuid4(),
            "kind": kind,
            "payload": encode(payload),
            "payload_hash": digest(payload),
            "epoch": epoch,
        },
    )
    return seq


def journal(conn, run_id, after=0, limit=5000):
    return rows(
        conn,
        """SELECT run_id,seq,producer_event_id,kind,payload,occurred_at,recorded_at
      FROM run_journal WHERE run_id=:id AND seq>:after ORDER BY seq LIMIT :limit""",
        id=run_id,
        after=after,
        limit=limit,
    )
