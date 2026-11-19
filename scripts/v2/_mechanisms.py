"""SQL-free, barrier-controlled schedules for B's whitelisted transaction adapters."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import time


def non_repeatable_read(adapter, isolation):
    """adapter.transaction(isolation) exposes read_counter/write_counter/commit."""
    first_read, updated = Event(), Event()

    def reader():
        with adapter.transaction(isolation) as transaction:
            first = transaction.read_counter()
            first_read.set()
            if not updated.wait(5):
                raise TimeoutError("Writer did not reach its commit barrier")
            second = transaction.read_counter()
            transaction.commit()
            return {"first": first, "second": second}

    def writer():
        if not first_read.wait(5):
            raise TimeoutError("Reader did not reach its first read barrier")
        with adapter.transaction("READ COMMITTED") as transaction:
            transaction.write_counter(adapter.next_value)
            transaction.commit()
        updated.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        reading, writing = pool.submit(reader), pool.submit(writer)
        writing.result(timeout=10)
        result = reading.result(timeout=10)
    result["passed"] = (
        result["first"] != result["second"]
        if isolation == "READ COMMITTED"
        else result["first"] == result["second"]
    )
    return result


def write_skew(adapter, isolation, *, max_retries=2):
    """Both transactions read both duty rows before updating their own row.

    Adapter supplies read_active(), set_inactive(row), commit(), transaction()
    and sqlstate exceptions. Retrying always starts a fresh transaction/read.
    """
    barrier = Barrier(2)

    def worker(row):
        errors = []
        for attempt in range(max_retries + 1):
            try:
                with adapter.transaction(isolation) as transaction:
                    active = transaction.read_active()
                    if attempt == 0:
                        barrier.wait(timeout=5)
                    if sum(active.values()) > 1:
                        transaction.set_inactive(row)
                    transaction.commit()
                return {"row": row, "retries": attempt, "sqlstates": errors}
            except Exception as exc:
                if getattr(exc, "sqlstate", None) != "40001" or attempt == max_retries:
                    raise
                errors.append("40001")
        raise RuntimeError("Retry budget exhausted")

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(worker, (1, 2)))
    with adapter.transaction("READ COMMITTED") as transaction:
        remaining = sum(transaction.read_active().values())
        transaction.commit()
    return {
        "records": records,
        "active_rows": remaining,
        "passed": remaining >= 1 and any(record["sqlstates"] for record in records)
        if isolation == "SERIALIZABLE"
        else remaining == 0,
    }


def queue_contention(adapter, *, strategy, claimers, jobs=1000):
    """Short adapter.claim() transactions finish before simulated_work/complete."""
    if (
        strategy not in {"blocking", "skip_locked"}
        or claimers not in {1, 2, 4, 8}
        or jobs != 1000
    ):
        raise ValueError("Unsupported queue experiment parameters")
    barrier = Barrier(claimers)

    def claimant(index):
        barrier.wait(timeout=5)
        records = []
        while True:
            started = time.perf_counter()
            job = adapter.claim(strategy, index)
            if job is None:
                break
            latency = (time.perf_counter() - started) * 1000
            adapter.simulated_work(job)
            adapter.complete(job, index)
            records.append({"job_id": str(job), "claimer": index, "claim_ms": latency})
        return records

    beginning = time.perf_counter()
    with ThreadPoolExecutor(max_workers=claimers) as pool:
        results = list(pool.map(claimant, range(claimers)))
    records = [record for result in results for record in result]
    duplicates = len(records) - len({record["job_id"] for record in records})
    elapsed = time.perf_counter() - beginning
    return {
        "records": records,
        "duplicates": duplicates,
        "completed": len(records),
        "claimer_counts": [len(result) for result in results],
        "jobs_per_second": len(records) / elapsed,
        "passed": duplicates == 0 and len(records) == jobs,
    }
