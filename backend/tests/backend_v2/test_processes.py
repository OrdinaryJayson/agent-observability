import os
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import text


def launch(*args):
    script = Path(__file__).with_name("worker_probe.py")
    return subprocess.Popen(
        [sys.executable, str(script), *args],
        env={**os.environ, "PYTHONUTF8": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def finish(process):
    try:
        stdout, stderr = process.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise AssertionError("Owned Worker process exceeded 15-second test budget")
    assert process.returncode == 0, stdout + stderr


def test_two_worker_processes_commit_each_run_once(prepared, db):
    prepared["start"]("process-run-0001")
    prepared["start"]("process-run-0002")
    workers = [launch("run", "process-a"), launch("run", "process-b")]
    try:
        for process in workers:
            finish(process)
    finally:
        for process in workers:
            if process.poll() is None:
                process.kill()
                process.communicate()
    with db.connect() as conn:
        assert (
            conn.scalar(text("SELECT count(*) FROM runs WHERE status='SUCCESS'")) == 2
        )
        assert conn.scalar(text("SELECT count(*) FROM run_summaries")) == 2
        assert (
            conn.scalar(
                text("SELECT count(*) FROM run_journal WHERE kind='run.finished'")
            )
            == 2
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM run_executions WHERE worker_id IS NOT NULL")
            )
            == 0
        )
        assert conn.scalar(text("SELECT count(*) FROM spans")) == 14


def test_worker_process_death_and_recovery(prepared, db, tmp_path):
    prepared["start"]("process-crash-0001")
    marker = tmp_path / "claimed.txt"
    dying = launch("hold", "crashed-owner", str(marker))
    try:
        deadline = time.monotonic() + 10
        while (
            not marker.exists() and time.monotonic() < deadline and dying.poll() is None
        ):
            time.sleep(0.02)
        assert marker.exists(), "Worker did not reach the registered claim barrier"
        dying.kill()
        dying.communicate(timeout=5)
    finally:
        if dying.poll() is None:
            dying.kill()
            dying.communicate()
    # Advance only this isolated lease, avoiding a 15-second wall-clock sleep.
    with db.begin() as conn:
        conn.execute(
            text(
                "UPDATE run_executions SET lease_expires_at=clock_timestamp()-interval '1 second'"
            )
        )
    finish(launch("run", "replacement-owner"))
    with db.connect() as conn:
        assert conn.scalar(text("SELECT status FROM runs")) == "SUCCESS"
        assert conn.scalar(text("SELECT lease_epoch FROM run_executions")) == 2
        assert conn.scalar(text("SELECT recovery_count FROM run_executions")) == 1
        assert (
            conn.scalar(
                text("SELECT count(*) FROM run_journal WHERE kind='run.recovering'")
            )
            == 1
        )
        assert conn.scalar(text("SELECT count(*) FROM run_summaries")) == 1
