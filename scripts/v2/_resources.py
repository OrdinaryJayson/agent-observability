"""Bounded resource sampling through a B/operator read-only metrics adapter."""

import importlib
import math
from threading import Event, Thread
import time


class ResourceSampler:
    def __init__(self, module=None):
        self.adapter = importlib.import_module(module) if module else None
        self.records = []
        self.errors = []
        self.stop_event = Event()
        self.thread = None

    def start(self):
        if self.adapter is None:
            return

        def sample():
            while not self.stop_event.is_set():
                try:
                    metrics = self.adapter.sample_resources()
                    record = {"monotonic_seconds": time.monotonic()}
                    for key in (
                        "database_connections",
                        "api_rss_bytes",
                        "worker_rss_bytes",
                    ):
                        number = metrics.get(key)
                        if number is not None and (
                            type(number) not in (int, float)
                            or not math.isfinite(number)
                            or number < 0
                        ):
                            raise ValueError("Invalid resource measurement")
                        record[key] = number
                    self.records.append(record)
                except Exception as exc:
                    self.errors.append(type(exc).__name__)
                self.stop_event.wait(0.1)

        self.thread = Thread(target=sample, daemon=True)
        self.thread.start()

    def finish(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        return {
            "samples": self.records,
            "errors": self.errors,
            "peaks": {
                key: max(
                    (record[key] for record in self.records if record[key] is not None),
                    default=None,
                )
                for key in ("database_connections", "api_rss_bytes", "worker_rss_bytes")
            },
            "available": self.adapter is not None,
        }
