import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.exc import DBAPIError

from app.core.config import database_url
from app.lab import database as lab_db
from app.lab.transactions import DutyTransaction, prepare
from app.lab.worker import work
from app.repositories.v2 import encode
from app.services import v2_lab


@pytest.fixture
def lab(db, monkeypatch):
    monkeypatch.setenv("EXPERIMENT_ENABLED", "true")
    monkeypatch.setenv(
        "EXPERIMENT_DATABASE_URL",
        make_url(database_url())
        .set(database="agent_observability_v2_lab")
        .render_as_string(hide_password=False),
    )
    dataset_id = uuid4()
    size = int(os.getenv("B_V2_EVIDENCE_SPANS", "1000"))
    assert 1000 <= size <= 1000000 and size % 500 == 0
    with db.begin() as conn:
        conn.execute(
            text("""INSERT INTO dataset_manifests(dataset_id,name,purpose,state,seed,config,actual_counts,content_hash,generator_version)
          VALUES(:id,'B fixed DB fixture - not C Loader','BENCHMARK','READY',42,'{"b_test_fixture": true}',CAST(:counts AS jsonb),NULL,'B-test-only-unverified-manifest')"""),
            {
                "id": dataset_id,
                "counts": encode({"spans": size, "runs": size // 500, "agents": 8}),
            },
        )
    with lab_db.engine().begin() as conn:
        from app.lab.bootstrap import bootstrap

        bootstrap(conn)
        lab_db.create_layout(conn, dataset_id)
        task = conn.scalar(
            text(
                "INSERT INTO tasks(title) VALUES('Isolated fixed fixture') RETURNING task_id"
            )
        )
        agents = list(
            conn.execute(
                text(
                    "INSERT INTO agents(name,role) SELECT 'Fixed '||i,'research' FROM generate_series(1,8) i RETURNING agent_id"
                )
            ).scalars()
        )
        for run_no in range(size // 500):
            run_id = uuid4()
            day = run_no * 89 // (size // 500 - 1)
            conn.execute(
                text("""INSERT INTO runs(run_id,task_id,trace_id,source_type,status,started_at,ended_at)
              VALUES(:run,:task,:trace,'SIMULATED','SUCCESS',TIMESTAMPTZ '2026-01-01 00:00:00Z'+make_interval(days=>:day),
              TIMESTAMPTZ '2026-01-01 00:00:10Z'+make_interval(days=>:day))"""),
                {"run": run_id, "task": task, "trace": uuid4().hex, "day": day},
            )
            conn.execute(
                text("""INSERT INTO spans(run_id,span_id,parent_span_id,operation_type,span_name,status,start_time,end_time,input_tokens,output_tokens,attributes,agent_id)
              SELECT :run,lpad(to_hex(CAST(:base AS integer)+i),16,'0'),CASE WHEN i=0 THEN NULL ELSE lpad(to_hex(CAST(:base AS integer)),16,'0') END,
                CASE WHEN i=0 THEN 'WORKFLOW' ELSE 'LLM' END,'Fixed',CASE WHEN i%10=1 THEN 'ERROR' ELSE 'SUCCESS' END,
                TIMESTAMPTZ '2026-01-01 00:00:00Z'+make_interval(days=>:day,secs=>i*0.01),TIMESTAMPTZ '2026-01-01 00:00:10Z'+make_interval(days=>:day),
                CASE WHEN i=0 THEN NULL ELSE 50 END,CASE WHEN i=0 THEN NULL ELSE 20 END,
                jsonb_set(attrs,'{padding}',to_jsonb(repeat('x',128-octet_length(attrs::text)))),
                CASE WHEN i=0 THEN NULL ELSE CAST(:agent AS uuid) END
              FROM generate_series(0,499) i CROSS JOIN LATERAL
                (SELECT jsonb_build_object('region',CASE WHEN i%100=0 THEN 'rare' ELSE 'common' END,
                   'tool_category','search','payload_size',128,'padding','') AS attrs) a"""),
                {
                    "run": run_id,
                    "base": run_no * 500 + 1,
                    "day": day,
                    "agent": agents[run_no % 8],
                },
            )
        counts = conn.execute(
            text(
                "SELECT count(*),min(octet_length(attributes::text)),max(octet_length(attributes::text)) FROM spans"
            )
        ).one()
        assert tuple(counts) == (size, 128, 128)
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM (SELECT run_id FROM spans GROUP BY run_id HAVING count(*) FILTER(WHERE parent_span_id IS NULL)<>1) invalid"
                )
            )
            == 0
        )
    yield dataset_id
    lab_db.cleanup(dataset_id, confirm=True)
    lab_db.engine().dispose()
    lab_db._engine.cache_clear()


def request(dataset_id, case="PAGINATION", parameters=None):
    return {
        "dataset_id": str(dataset_id),
        "case_code": case,
        "parameters": parameters or {"rank": 0, "limit": 50},
        "seed": 42,
        "warmups": 3,
        "repetitions": 15,
    }


@pytest.mark.parametrize(
    "case,parameters,variants",
    [
        ("INDEX_SELECTIVITY", {"query": "TRACE", "selectivity": 0.001}, 3),
        ("INDEX_SELECTIVITY", {"query": "ERROR", "selectivity": 0.01}, 3),
        ("JSONB_GIN", {"selectivity": 0.01}, 3),
        ("PAGINATION", {"rank": 0, "limit": 50}, 2),
        ("PAGINATION", {"rank": 10000, "limit": 50}, 2),
        ("PAGINATION", {"rank": 100000, "limit": 50}, 2),
        ("AGGREGATION", {"window_days": 90}, 3),
    ],
)
def test_query_experiments_real_samples(lab, client, db, case, parameters, variants):
    body = request(lab, case, parameters)
    response = client.post(
        "/api/v2/experiments",
        json=body,
        headers={"Idempotency-Key": "experiment-fixed-1"},
    )
    assert response.status_code == 202, response.text
    experiment_id = response.json()["data"]["experiment_id"]
    assert (
        client.post(
            "/api/v2/experiments",
            json=body,
            headers={"Idempotency-Key": "experiment-fixed-1"},
        ).json()
        == response.json()
    )
    work("lab-test", once=True)
    result = client.get(f"/api/v2/experiments/{experiment_id}").json()["data"]
    assert result["status"] == "SUCCESS", result
    assert result["trial_count"] == variants
    assert result["sample_count"] == variants * 18
    exported = client.get(f"/api/v2/experiments/{experiment_id}/export").json()
    assert len(exported["samples"]) == variants * 18
    assert all(s["correctness"]["passed"] for s in exported["samples"])
    if not (
        case == "PAGINATION"
        and parameters["rank"] >= int(os.getenv("B_V2_EVIDENCE_SPANS", "1000"))
    ):
        assert all(s["plan"]["Plan"] for s in exported["samples"])
        assert all(t["summary"]["n"] == 15 for t in exported["trials"])
    else:
        assert all(t["summary"]["n"] == 0 for t in exported["trials"])
    assert client.get(
        f"/api/v2/experiments/{experiment_id}/export?format=csv"
    ).text.startswith("trial_id,repetition")
    first_trial = exported["trials"][0]["trial_id"]
    samples = client.get(
        f"/api/v2/experiments/{experiment_id}/samples",
        params={"trial_id": first_trial, "limit": 10},
    ).json()
    assert samples["meta"]["has_more"]
    if output := os.getenv("B_V2_EVIDENCE_DIR"):
        from app.core.config import ROOT
        from app.contracts.v2 import digest

        destination = Path(output).resolve()
        assert destination.is_relative_to((ROOT / "backend/var").resolve())
        destination.mkdir(parents=True, exist_ok=True)
        filename = f"{os.getenv('B_V2_EVIDENCE_SPANS', '1000')}-{case}-{digest(parameters)[:12]}.json"
        (destination / filename).write_text(
            json.dumps(exported, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def test_experiment_lock_cancel_and_validation(lab, client, db):
    body = request(lab)
    for changed in (
        {**body, "warmups": 1},
        {**body, "parameters": {"rank": 0, "limit": 50, "sql": "DROP TABLE spans"}},
    ):
        assert (
            client.post(
                "/api/v2/experiments",
                json=changed,
                headers={"Idempotency-Key": "experiment-invalid"},
            ).status_code
            == 422
        )
    accepted = client.post(
        "/api/v2/experiments",
        json=body,
        headers={"Idempotency-Key": "experiment-queued"},
    ).json()["data"]
    with lab_db.engine().connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lab_db.LAB_LOCK})
        lock.commit()
        work("second-lab", once=True)
        assert (
            client.get(f"/api/v2/experiments/{accepted['experiment_id']}").json()[
                "data"
            ]["status"]
            == "QUEUED"
        )
        lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lab_db.LAB_LOCK})
        lock.commit()
    cancelled = client.post(
        f"/api/v2/experiments/{accepted['experiment_id']}/cancel", json={}
    ).json()["data"]
    assert cancelled["status"] == "CANCELLED"
    assert lab_db.cleanup(lab)["deleted"] is False


@pytest.mark.parametrize(
    "variant,second", [("read_committed", 1), ("repeatable_read", 2)]
)
def test_mvcc_controlled_visibility(lab, variant, second):
    with lab_db.engine().begin() as conn:
        lab_db.configure(conn, lab)
        prepare(conn)
    with (
        DutyTransaction(lab, variant) as first,
        DutyTransaction(lab, "read_committed") as writer,
    ):
        assert first.active_count() == 2
        writer.set_inactive(1)
        writer.commit()
        assert first.active_count() == second
        first.commit()


@pytest.mark.parametrize(
    "variant,expected", [("repeatable_read", 0), ("serializable", 1)]
)
def test_write_skew_and_serialization_retry(lab, variant, expected):
    with lab_db.engine().begin() as conn:
        lab_db.configure(conn, lab)
        prepare(conn)
    # Explicit barriers: both reads precede either write; no sleep-based race.
    with DutyTransaction(lab, variant) as a, DutyTransaction(lab, variant) as b:
        assert a.active_count() == b.active_count() == 2
        a.set_inactive(1)
        b.set_inactive(2)
        a.commit()
        if variant == "serializable":
            with pytest.raises(DBAPIError) as error:
                b.commit()
            assert error.value.orig.sqlstate == "40001"
        else:
            b.commit()
    with DutyTransaction(lab, variant) as retry:
        assert retry.active_count() == expected
        # Re-read on retry preserves the cross-row application invariant.
        if retry.active_count() > 1:
            retry.set_inactive(2)
        retry.commit()


def test_lab_role_cannot_create_in_public(lab):
    with pytest.raises(DBAPIError) as error:
        with lab_db.engine().begin() as conn:
            conn.execute(text("SET LOCAL ROLE observability_lab"))
            conn.execute(text("CREATE TABLE public.denied(id int)"))
    assert error.value.orig.sqlstate == "42501"


def test_legacy_experiment_uses_separate_lab_and_original_json_interface(
    lab, client, monkeypatch, tmp_path
):
    from app.services import benchmarks

    monkeypatch.setenv("BENCHMARK_ENABLED", "true")
    monkeypatch.setattr(benchmarks, "RESULTS_PATH", tmp_path / "benchmarks.json")
    observed = []
    original = benchmarks.create_engine

    def record_target(url, **kwargs):
        observed.append(make_url(url).database)
        kwargs["connect_args"]["options"] += " -c role=observability_lab"
        return original(url, **kwargs)

    monkeypatch.setattr(benchmarks, "create_engine", record_target)
    response = client.post(
        "/api/v1/benchmarks/run",
        json={"case_code": "TRACE_QUERY_INDEX", "dataset_size": 1000},
    )
    assert response.status_code == 201, response.text
    assert observed == ["agent_observability_v2_lab"]
    assert client.get("/api/v1/benchmarks/results").json()["meta"]["total"] == 1


def test_queue_experiment_1000_jobs_15_measured_pairs(lab, client):
    body = request(lab, "QUEUE_CONTENTION", {"claimers": 2, "jobs": 1000})
    response = client.post(
        "/api/v2/experiments", json=body, headers={"Idempotency-Key": "queue-full-0001"}
    )
    assert response.status_code == 202
    experiment_id = response.json()["data"]["experiment_id"]
    work("lab-queue", once=True)
    result = client.get(f"/api/v2/experiments/{experiment_id}/export").json()
    assert result["experiment"]["status"] == "SUCCESS", result["experiment"]
    assert len(result["samples"]) == 36
    assert all(
        sample["correctness"]["checks"]["unique"] == 1000
        for sample in result["samples"]
    )
    assert all(
        sample["metrics"]["extra"]["duplicate_completions"] == 0
        for sample in result["samples"]
    )


@pytest.mark.parametrize("fault", ["timeout", "cancel"])
def test_lab_fault_retains_completed_samples(lab, client, monkeypatch, fault):
    from app.lab import runner

    response = client.post(
        "/api/v2/experiments",
        json=request(lab),
        headers={"Idempotency-Key": "lab-fault-0001"},
    )
    experiment_id = response.json()["data"]["experiment_id"]
    original = runner.persist_sample
    count = 0

    def after_sample(*args):
        nonlocal count
        original(*args)
        count += 1
        if count == 2:
            if fault == "cancel":
                v2_lab.cancel(experiment_id)
            else:

                def timed_out(conn, sql, parameters):
                    conn.execute(text("SET LOCAL statement_timeout='50ms'"))
                    conn.execute(text("SELECT pg_sleep(1)"))

                monkeypatch.setattr(runner.measure, "query", timed_out)

    monkeypatch.setattr(runner, "persist_sample", after_sample)
    work("lab-fault", once=True)
    result = client.get(f"/api/v2/experiments/{experiment_id}").json()["data"]
    assert result["sample_count"] == (3 if fault == "timeout" else 2)
    assert result["status"] == ("FAILED" if fault == "timeout" else "CANCELLED")
    assert result["error_code"] == (
        "EXPERIMENT_TIMEOUT" if fault == "timeout" else "EXPERIMENT_CANCELLED"
    )
    with lab_db.engine().connect() as conn:
        assert conn.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": lab_db.LAB_LOCK}
        )
        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lab_db.LAB_LOCK})
        conn.commit()


def test_lab_process_mutex_and_abandoned_run(lab, client, db):
    import os
    import subprocess
    import sys

    response = client.post(
        "/api/v2/experiments",
        json=request(lab),
        headers={"Idempotency-Key": "lab-process-0001"},
    )
    experiment_id = response.json()["data"]["experiment_id"]

    def child():
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.lab.worker",
                "--runner-id",
                "second-process",
                "--once",
            ],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert result.returncode == 0, result.stderr

    with lab_db.engine().connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lab_db.LAB_LOCK})
        lock.commit()
        v2_lab.claim("abandoned-test")
        child()
        with db.connect() as conn:
            assert v2_lab.experiment(conn, experiment_id)["status"] == "RUNNING"
        lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lab_db.LAB_LOCK})
        lock.commit()
    child()
    with db.connect() as conn:
        abandoned = v2_lab.experiment(conn, experiment_id)
        assert abandoned["status"] == "FAILED"
        assert abandoned["error_code"] == "EXPERIMENT_INTERRUPTED"
