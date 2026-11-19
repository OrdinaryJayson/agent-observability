import base64
import json

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from app.contracts.v2 import digest
from app.core.errors import AppError
from app.repositories.v2 import one, rows, journal
from app.services import v2_engine


def cursor_page(conn, sql, parameters, query, keys, order):
    filters = query.model_dump(mode="json", by_alias=True, exclude={"cursor", "limit"})
    signature = digest(filters)
    condition = "TRUE"
    if query.cursor:
        try:
            raw = json.loads(
                base64.b64decode(
                    query.cursor + "=" * (-len(query.cursor) % 4),
                    altchars=b"-_",
                    validate=True,
                )
            )
            if (
                not isinstance(raw, dict)
                or set(raw) != {"v", "order", "filter_hash", "keys"}
                or type(raw["v"]) is not int
                or raw["v"] != 1
                or raw["order"] != order
                or raw["filter_hash"] != signature
                or not isinstance(raw["keys"], list)
                or len(raw["keys"]) != len(keys)
            ):
                raise ValueError("Invalid cursor")
            for index, ((column, cast, validator), value) in enumerate(
                zip(keys, raw["keys"])
            ):
                if cast in {"bigint", "integer"}:
                    bits = 63 if cast == "bigint" else 31
                    if type(value) is not int or not -(2**bits) <= value < 2**bits:
                        raise ValueError("Invalid integer cursor key")
                elif not isinstance(value, str):
                    raise ValueError("Invalid text cursor key")
                parameters[f"c{index}"] = validator(value)
            condition = (
                "("
                + ",".join(k[0] for k in keys)
                + ") < ("
                + ",".join(f"CAST(:c{i} AS {k[1]})" for i, k in enumerate(keys))
                + ")"
            )
        except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
            raise AppError(
                422, "VALIDATION_ERROR", "Cursor does not match this query"
            ) from exc
    result = rows(
        conn,
        f"SELECT * FROM ({sql}) AS page WHERE {condition} ORDER BY "
        + ",".join(k[0] + " DESC" for k in keys)
        + " LIMIT :page_limit",
        **parameters,
        page_limit=query.limit + 1,
    )
    more = len(result) > query.limit
    result = result[: query.limit]
    token = None
    if more:
        token = (
            base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "v": 1,
                        "order": order,
                        "filter_hash": signature,
                        "keys": jsonable_encoder([result[-1][k[0]] for k in keys]),
                    },
                    separators=(",", ":"),
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
    return {
        "data": result,
        "meta": {"limit": query.limit, "next_cursor": token, "has_more": more},
    }


def run_view(conn, run_id):
    result = one(
        conn,
        """SELECT r.*,e.version_id,w.name AS workflow_name,v.version_no,
      coalesce(e.config->>'mode','LEGACY') AS mode,
      coalesce(e.execution_state,CASE WHEN r.status='RUNNING' THEN 'RUNNING' ELSE 'FINISHED' END) AS execution_state,
      e.queued_at,e.execution_started_at,e.execution_ended_at,s.queue_duration_ms,s.execution_duration_ms,
      s.logical_duration_ms,coalesce(e.last_seq,0) AS last_seq,e.cancel_requested_at,coalesce(e.recovery_count,0) AS recovery_count,
      f.span_count,f.error_count,e.checkpoint AS private_checkpoint,jsonb_array_length(v.definition->'nodes') AS private_node_count
      FROM runs r JOIN v_run_facts f ON f.run_id=r.run_id LEFT JOIN run_executions e ON e.run_id=r.run_id LEFT JOIN workflow_versions v ON v.version_id=e.version_id
      LEFT JOIN workflows w ON w.workflow_id=v.workflow_id LEFT JOIN run_summaries s ON s.run_id=r.run_id WHERE r.run_id=:id""",
        id=run_id,
    )
    checkpoint = result.pop("private_checkpoint") or {}
    total = result.pop("private_node_count")
    result["progress"] = 1.0 if result["status"] != "RUNNING" else 0.0
    if result["version_id"]:
        states = checkpoint.get("node_states", {})
        result["progress"] = (
            sum(
                n["state"] in {"SUCCESS", "ERROR", "SKIPPED", "CANCELLED"}
                for n in states.values()
            )
            / total
            if total
            else 0.0
        )
        if not checkpoint and result["status"] == "CANCELLED":
            result["progress"] = 1.0
    return result


def snapshot(conn, run_id):
    run = run_view(conn, run_id)
    events = journal(conn, run_id)
    complete = bool(
        events
        and events[-1]["kind"] == "run.finished"
        and events[-1]["payload"]["projection_complete"]
    )
    if run["mode"] == "LEGACY" or (run["status"] != "RUNNING" and complete):
        spans = rows(
            conn,
            "SELECT * FROM spans WHERE run_id=:id ORDER BY start_time,span_id",
            id=run_id,
        )
        live = []
        for span in spans:
            span.pop("span_pk", None)
            span.pop("run_id", None)
            span["state"] = span.pop("status")
            attrs = span["attributes"]
            span.update(
                node_key=attrs.get("node_key") if run["mode"] != "LEGACY" else None,
                role_key=attrs.get("role_key") if run["mode"] != "LEGACY" else None,
                attempt_no=attrs.get("attempt_no", 1) if run["mode"] != "LEGACY" else 1,
            )
            live.append(span)
        projection = {"nodes": [], "spans": live, "links": []}
        if run["mode"] != "LEGACY":
            metadata = one(
                conn,
                "SELECT e.checkpoint,v.definition FROM run_executions e JOIN workflow_versions v USING(version_id) WHERE run_id=:id",
                id=run_id,
            )
            state = "CANCELLED" if run["status"] == "CANCELLED" else "PENDING"
            for node in metadata["definition"]["nodes"]:
                saved = (
                    metadata["checkpoint"]
                    .get("node_states", {})
                    .get(node["node_key"], {})
                )
                projection["nodes"].append(
                    {
                        "node_key": node["node_key"],
                        "state": saved.get("state", state),
                        "attempt_no": saved.get("attempt_no", 0),
                        "span_ids": saved.get("span_ids", []),
                    }
                )
            projection["links"] = rows(
                conn,
                "SELECT source_span_id,target_span_id,link_type FROM span_links WHERE run_id=:id ORDER BY source_span_id,target_span_id,link_type",
                id=run_id,
            )
        count = conn.execute(
            text("SELECT count(*) FROM span_events WHERE run_id=:id"), {"id": run_id}
        ).scalar_one()
        complete = run["status"] != "RUNNING" if run["mode"] == "LEGACY" else complete
    elif any(e["kind"].startswith(("span.", "node.")) for e in events):
        projection = v2_engine.reduce_journal(jsonable_encoder(events))
        count = len(projection["events"])
        complete = bool(
            events
            and events[-1]["kind"] == "run.finished"
            and events[-1]["payload"]["projection_complete"]
        )
    else:
        definition = one(
            conn,
            "SELECT definition FROM workflow_versions WHERE version_id=:id",
            id=run["version_id"],
        )["definition"]
        state = "CANCELLED" if run["status"] == "CANCELLED" else "PENDING"
        projection = {
            "nodes": [
                {
                    "node_key": n["node_key"],
                    "state": state,
                    "attempt_no": 0,
                    "span_ids": [],
                }
                for n in definition["nodes"]
            ],
            "spans": [],
            "links": [],
        }
        count = 0
    result = {
        "run": run,
        "seq": run["last_seq"],
        "nodes": projection["nodes"],
        "spans": projection["spans"],
        "links": projection["links"],
        "event_count": count,
        "projection_complete": complete,
    }
    if (
        len(json.dumps(jsonable_encoder(result), ensure_ascii=False).encode())
        > 2 * 1024 * 1024
    ):
        raise AppError(422, "BUDGET_EXCEEDED", "Snapshot exceeds 2 MiB")
    return result


def journal_page(conn, run_id, after, limit):
    execution = one(
        conn,
        "SELECT last_seq,execution_state FROM run_executions WHERE run_id=:id",
        id=run_id,
    )
    if after > execution["last_seq"]:
        raise AppError(422, "VALIDATION_ERROR", "Cursor is ahead of the journal")
    minimum = conn.execute(
        text("SELECT min(seq) FROM run_journal WHERE run_id=:id"), {"id": run_id}
    ).scalar_one()
    if minimum is not None and after < minimum - 1:
        raise AppError(410, "CURSOR_EXPIRED", "Get a fresh snapshot")
    data = journal(conn, run_id, after, limit)
    return {
        "data": data,
        "meta": {
            "next_after_seq": data[-1]["seq"] if data else after,
            "has_more": bool(data and data[-1]["seq"] < execution["last_seq"]),
            "snapshot_seq": execution["last_seq"],
        },
    }
