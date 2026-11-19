"""V2-owned fixtures; never alter the frozen shared fixtures."""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import make_url, text

from app.core.config import database_url
from app.core.database import get_engine
from app.models.tables import tables


@pytest.fixture(scope="session")
def database():
    url = make_url(os.getenv("TEST_DATABASE_URL") or database_url())
    if not (url.database or "").endswith("_v2_test"):
        pytest.fail("B V2 tests require a dedicated *_v2_test database")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    get_engine.cache_clear()
    tables.cache_clear()
    from app.migrate import migrate

    migrate()
    yield get_engine()
    get_engine().dispose()
    get_engine.cache_clear()
    tables.cache_clear()
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous


@pytest.fixture
def db(database):
    with database.begin() as conn:
        conn.execute(
            text("""TRUNCATE experiment_samples,experiment_trials,experiment_runs,dataset_manifests,
          request_keys,analysis_reports,span_links,run_journal,run_summaries,run_executions,
          workflow_versions,workflows,audit_log,span_events,spans,runs,tasks,agents CASCADE""")
        )
        conn.execute(text("REFRESH MATERIALIZED VIEW mv_daily_metrics"))
    return database


@pytest.fixture
def samples():
    return json.loads(
        (Path(__file__).resolve().parents[3] / "contracts/v2/examples.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.fixture
def prepared(db, samples, monkeypatch):
    from uuid import UUID
    from app.contracts.v2 import digest, RunStart
    from app.services import v2_engine, v2_workflows, v2_runs
    from app.repositories.v2 import one

    monkeypatch.setattr(
        v2_engine, "validate_workflow", lambda definition: {"valid": True, "errors": []}
    )
    with db.begin() as conn:
        one(
            conn,
            "INSERT INTO agents(agent_id,name,role) VALUES(:id,'Fixed','research') RETURNING *",
            id=UUID(samples["ids"]["agent_id"]),
        )
        task = one(conn, "INSERT INTO tasks(title) VALUES('V2 test') RETURNING *")
    workflow = v2_workflows.create(
        {
            "name": "Parallel",
            "description": None,
            "draft": samples["workflow_definitions"]["parallel"],
        }
    )
    version = v2_workflows.publish(
        workflow["workflow_id"], 1, digest(workflow["draft"])
    )
    request = RunStart(
        **{
            **samples["run_start"],
            "version_id": version["version_id"],
            "dataset_id": None,
        }
    )
    return {
        "task": task,
        "workflow": workflow,
        "version": version,
        "request": request,
        "start": lambda key="request-key-0001": v2_runs.start(
            task["task_id"], request, key
        ),
    }


@pytest.fixture
def running(prepared, samples, monkeypatch):
    import copy
    from app.services import v2_engine, v2_runs

    accepted = prepared["start"]()
    claim = v2_runs.claim("worker-a")
    batches = copy.deepcopy(samples["journal_batches"])
    for batch in batches:
        batch["run_id"] = accepted["data"]["run_id"]
        batch["checkpoint"]["definition_hash"] = prepared["version"]["definition_hash"]
    final = copy.deepcopy(samples["snapshot"])
    spans = []
    for live in final["spans"]:
        span = {
            k: v
            for k, v in live.items()
            if k not in {"node_key", "role_key", "attempt_no", "state"}
        }
        span["status"] = live["state"]
        span["attributes"] = {
            **span["attributes"],
            **{k: live[k] for k in ("node_key", "role_key", "attempt_no")},
        }
        spans.append(span)
    closed = {
        "spans": spans,
        "events": [
            e["payload"] for e in samples["journal"] if e["kind"] == "span.event"
        ],
        "links": final["links"],
        "nodes": final["nodes"],
        "final_status": "SUCCESS",
        "error_summary": None,
        "time_basis": "REALTIME",
        "logical_duration_ms": 600,
    }

    def fixed_projection(events):
        # A fixed C result from frozen fixtures, not an alternative reducer.
        if len(events) <= 8:
            partial = samples["running_snapshot"]
            return {
                "nodes": partial["nodes"],
                "spans": partial["spans"],
                "links": partial["links"],
                "events": [],
                "closed_result": None,
            }
        return {
            "nodes": final["nodes"],
            "spans": final["spans"],
            "links": final["links"],
            "events": closed["events"],
            "closed_result": closed,
        }

    monkeypatch.setattr(v2_engine, "reduce_journal", fixed_projection)
    return claim, batches, closed
