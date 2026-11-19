from copy import deepcopy
from threading import Lock

import pytest

from _mechanisms import non_repeatable_read, queue_contention, write_skew


class SerializationFailure(Exception):
    sqlstate = "40001"


class TransactionAdapter:
    """Deterministic schedule oracle only. This is not a PostgreSQL emulator."""

    def __init__(self):
        self.lock = Lock()
        self.counter, self.next_value, self.version = 0, 1, 0
        self.active = {1: True, 2: True}

    def transaction(self, isolation):
        owner = self

        class Transaction:
            def __enter__(self):
                with owner.lock:
                    self.snapshot = deepcopy(owner.active)
                    self.counter = owner.counter
                    self.version = owner.version
                self.row = None
                self.write = None
                return self

            def __exit__(self, *args):
                pass

            def read_counter(self):
                return owner.counter if isolation == "READ COMMITTED" else self.counter

            def write_counter(self, value):
                self.write = value

            def read_active(self):
                return (
                    deepcopy(owner.active)
                    if isolation == "READ COMMITTED"
                    else self.snapshot
                )

            def set_inactive(self, row):
                self.row = row

            def commit(self):
                with owner.lock:
                    if (
                        isolation == "SERIALIZABLE"
                        and self.row
                        and self.version != owner.version
                    ):
                        raise SerializationFailure()
                    if self.write is not None:
                        owner.counter = self.write
                        owner.version += 1
                    if self.row:
                        owner.active[self.row] = False
                        owner.version += 1

        return Transaction()


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_non_repeatable_read_barriers(isolation):
    assert non_repeatable_read(TransactionAdapter(), isolation)["passed"]


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_write_skew_barriers_and_fresh_retry(isolation):
    result = write_skew(TransactionAdapter(), isolation)
    assert result["passed"]
    if isolation == "SERIALIZABLE":
        assert sum(record["retries"] for record in result["records"]) == 1


def test_queue_driver_counts_duplicates_and_fairness():
    class Adapter:
        lock = Lock()
        jobs = list(range(1000))

        def claim(self, strategy, index):
            with self.lock:
                return self.jobs.pop() if self.jobs else None

        def simulated_work(self, job):
            pass

        def complete(self, job, index):
            pass

    result = queue_contention(Adapter(), strategy="skip_locked", claimers=4)
    assert result["passed"]
    assert result["completed"] == 1000
    assert sum(result["claimer_counts"]) == 1000
