"""Explicit large-data acceptance: pass this file to scripts/test_backend.py.

Not part of default unit-test discovery. This is B's fixed SQL dataset, not C's
HTTP data generator and not evidence that C's identity propagation is complete.
"""

from sqlalchemy import text


def test_hundred_thousand_spans_queries_and_reconciliation(client, db):
    with db.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO agents(agent_id, name, role)
            SELECT md5('agent-' || i)::uuid, 'Scale Agent ' || i, 'research'
            FROM generate_series(1,3) AS g(i)
        """)
        )
        conn.execute(
            text("""
            INSERT INTO tasks(task_id, title) VALUES (md5('scale-task')::uuid, 'B fixed scale test')
        """)
        )
        conn.execute(
            text("""
            INSERT INTO runs(run_id, task_id, trace_id, source_type, status, started_at, ended_at)
            SELECT md5('run-' || i)::uuid, md5('scale-task')::uuid, md5('trace-' || i),
                   'SIMULATED', CASE WHEN i % 5 = 0 THEN 'FAILED' ELSE 'SUCCESS' END,
                   timestamptz '2026-01-01 00:00:00+00' + i * interval '1 minute',
                   timestamptz '2026-01-01 00:00:00+00' + i * interval '1 minute' + interval '1 second'
            FROM generate_series(1,200) AS g(i)
        """)
        )
        conn.execute(
            text("""
            INSERT INTO spans(run_id, span_id, parent_span_id, agent_id, operation_type,
                              span_name, status, start_time, end_time, tool_name,
                              input_tokens, output_tokens, error_type)
            SELECT md5('run-' || i)::uuid, lpad(to_hex(j),16,'0'),
                   CASE WHEN j=1 THEN NULL WHEN j=2 THEN lpad('1',16,'0') ELSE lpad('2',16,'0') END,
                   CASE WHEN j=1 THEN NULL ELSE md5('agent-' || ((i-1)%3+1))::uuid END,
                   CASE WHEN j=1 THEN 'WORKFLOW' WHEN j=2 THEN 'AGENT' WHEN j=3 THEN 'LLM' ELSE 'TOOL' END,
                   'operation ' || j, CASE WHEN j % 100=0 THEN 'ERROR' ELSE 'SUCCESS' END,
                   timestamptz '2026-01-01 00:00:00+00' + i * interval '1 minute',
                   timestamptz '2026-01-01 00:00:00+00' + i * interval '1 minute' + interval '1 second',
                   CASE WHEN j>3 THEN 'search' ELSE NULL END,
                   CASE WHEN j=3 THEN 10 ELSE NULL END, CASE WHEN j=3 THEN 5 ELSE NULL END,
                   CASE WHEN j % 100=0 THEN 'ScaleError' ELSE NULL END
            FROM generate_series(1,200) AS r(i) CROSS JOIN generate_series(1,500) AS s(j)
        """)
        )
        conn.execute(
            text("""
            INSERT INTO span_events(event_id, run_id, span_id, event_name, severity, occurred_at)
            SELECT md5('event-' || i)::uuid, md5('run-' || i)::uuid, lpad(to_hex(100),16,'0'),
                   'tool.failed', 'ERROR', timestamptz '2026-01-01 00:00:00+00' + i * interval '1 minute'
            FROM generate_series(1,200) AS g(i)
        """)
        )
        conn.execute(text("ANALYZE spans"))
    overview = client.get("/api/v1/analytics/overview").json()["data"]
    assert overview == {
        "total_runs": 200,
        "success_runs": 160,
        "failed_runs": 40,
        "success_rate": 0.8,
        "avg_duration_ms": 1000,
        "p50_duration_ms": 1000,
        "p95_duration_ms": 1000,
        "total_input_tokens": 2000,
        "total_output_tokens": 1000,
        "total_spans": 100000,
    }
    agents = client.get("/api/v1/analytics/agents").json()["data"]
    assert [a["span_count"] for a in agents] == [67, 67, 66]
    assert sum(a["total_input_tokens"] for a in agents) == 2000
    assert sum(a["total_output_tokens"] for a in agents) == 1000
    tools = client.get("/api/v1/analytics/tools").json()["data"]
    assert tools == [
        {
            "tool_name": "search",
            "span_count": 99400,
            "error_count": 1000,
            "avg_duration_ms": 1000,
            "total_duration_ms": 99400000,
        }
    ]
    assert client.get("/api/v1/analytics/errors").json()["data"] == [
        {"error_type": "ScaleError", "count": 1000}
    ]
    assert (
        client.get("/api/v1/events", params={"error_type": "ScaleError"}).json()[
            "meta"
        ]["total"]
        == 200
    )
    runs = client.get("/api/v1/runs", params={"page_size": 100}).json()
    assert runs["meta"]["total"] == 200
    trace_id = runs["data"][0]["trace_id"]
    spans = []
    for page in range(1, 6):
        data = client.get(
            f"/api/v1/traces/{trace_id}/spans", params={"page": page, "page_size": 100}
        ).json()
        assert data["meta"]["total"] == 500
        spans.extend(data["data"])
    assert len({s["span_id"] for s in spans}) == 500
    print(
        "Verified 200 Runs, 100000 Spans, 200 Events, 3 Agents and exact aggregate reconciliation"
    )
