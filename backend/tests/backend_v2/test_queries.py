from uuid import uuid4

from sqlalchemy import text

from app.services import v2_analytics, v2_journal


def test_search_filters_cursor_and_catalog(running, client):
    _, batches, _ = running
    for batch in batches:
        v2_journal.commit("worker-a", batch)
    page = client.get("/api/v2/search/spans", params={"limit": 3})
    assert page.status_code == 200, page.text
    data = page.json()
    second = client.get(
        "/api/v2/search/spans",
        params={"limit": 100, "cursor": data["meta"]["next_cursor"]},
    ).json()
    assert len(data["data"] + second["data"]) == 7
    assert len({s["span_id"] for s in data["data"] + second["data"]}) == 7
    assert (
        client.get(
            "/api/v2/search/spans",
            params={"status": "ERROR", "cursor": data["meta"]["next_cursor"]},
        ).status_code
        == 422
    )
    assert (
        client.get("/api/v2/search/spans", params={"attributes": "[]"}).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v2/search/spans", params={"attributes": '{"unknown":true}'}
        ).json()["data"]
        == []
    )
    assert client.get("/api/v2/search/spans", params={"type": "LLM"}).status_code == 200
    assert (
        client.get("/api/v2/search/events", params={"mode": "REALTIME"}).status_code
        == 200
    )
    assert client.get("/api/v2/search/events?unexpected=true").status_code == 422
    catalog = client.get("/api/v2/database/catalog")
    assert catalog.status_code == 200, catalog.text
    assert len(catalog.json()["data"]["tables"]) == 18
    assert client.get("/api/v2/analytics/agents").status_code == 200
    overview = client.get("/api/v2/overview").json()["data"]
    assert overview["success_runs"] == 1 and overview["total_spans"] == 7
    assert overview["aggregate_status"]["stale"]
    assert (
        client.post("/api/v2/analytics/refresh", json={}).json()["data"]["stale"]
        is False
    )


def test_late_commit_below_max_sequence_still_detected(prepared, db):
    task_id = prepared["task"]["task_id"]

    def terminal(conn):
        run_id = uuid4()
        conn.execute(
            text("""INSERT INTO runs(run_id,task_id,trace_id,source_type,status,ended_at)
          VALUES(:id,:task,:trace,'SIMULATED','SUCCESS',now())"""),
            {"id": run_id, "task": task_id, "trace": uuid4().hex},
        )
        conn.execute(text("SELECT v2_legacy_summary(:id)"), {"id": run_id})

    with db.connect() as slow:
        tx = slow.begin()
        terminal(slow)
        with db.begin() as fast:
            terminal(fast)
        before = v2_analytics.refresh()
        assert not before["stale"]
        tx.commit()
    with db.connect() as conn:
        after = v2_analytics.aggregate_status(conn)
    assert after["watermark_max_seq"] == before["watermark_max_seq"]
    assert after["stale"]
    assert not v2_analytics.refresh()["stale"]


def test_refresh_mutex_preserves_snapshot(db):
    import pytest
    from app.core.errors import AppError

    with db.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(90624118)"))
        with pytest.raises(AppError) as error:
            v2_analytics.refresh()
        assert error.value.status == 409
        assert v2_analytics.aggregate_status(conn)["refreshing"]


def test_refresh_timeout_rolls_back_and_retains_previous_mv(prepared, db):
    import pytest
    from sqlalchemy import event
    from app.core.errors import AppError

    v2_analytics.refresh()
    with db.connect() as conn:
        previous = v2_analytics.aggregate_status(conn)

    def short_fault_budget(conn, cursor, statement, parameters, context, executemany):
        if statement == "SELECT public.v2_refresh_metrics()":
            cursor.execute("SET LOCAL statement_timeout='50ms'")

    with db.connect() as blocker:
        transaction = blocker.begin()
        blocker.execute(text("REFRESH MATERIALIZED VIEW mv_daily_metrics"))
        event.listen(db, "before_cursor_execute", short_fault_budget)
        try:
            with pytest.raises(AppError) as error:
                v2_analytics.refresh()
            assert error.value.code == "AGGREGATE_REFRESH_TIMEOUT"
        finally:
            event.remove(db, "before_cursor_execute", short_fault_budget)
            transaction.rollback()
    with db.connect() as conn:
        assert v2_analytics.aggregate_status(conn) == previous


def test_analysis_cache_does_not_require_reexecuting_c(
    running, client, samples, monkeypatch
):
    import copy
    from app.services import v2_engine

    claim, batches, _ = running
    for batch in batches:
        v2_journal.commit("worker-a", batch)
    calls = []

    def analyze(**kwargs):
        calls.append(kwargs)
        return copy.deepcopy(samples["analysis"])

    monkeypatch.setattr(v2_engine, "function", lambda name: analyze)
    path = f"/api/v2/runs/{claim['run_id']}/analysis"
    first = client.get(path)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["journal_seq"] == 25

    def unavailable(events):
        raise AssertionError("Cached report must not call C again")

    monkeypatch.setattr(v2_engine, "reduce_journal", unavailable)
    assert client.get(path).json() == first.json()
    assert len(calls) == 1


def test_overview_counts_committed_live_spans(running, client):
    claim, batches, _ = running
    v2_journal.commit("worker-a", batches[0])
    response = client.get("/api/v2/overview")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["total_spans"] == 5
    run = client.get(f"/api/v2/runs/{claim['run_id']}").json()["data"]
    assert run["span_count"] == 5
    assert run["progress"] == 0.2
