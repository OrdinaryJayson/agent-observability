import asyncio
from datetime import datetime, timedelta, timezone
import time

from .protocol import timestamp


class RealtimeClock:
    mode = "REALTIME"

    def __init__(self):
        self._origin = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._origin) * 1000

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def restore(self, logical_time_ms: float) -> None:
        self._origin = time.perf_counter() - logical_time_ms / 1000

    async def wait_ms(self, duration_ms: float) -> None:
        await asyncio.sleep(max(0, duration_ms) / 1000)


class VirtualClock:
    mode = "VIRTUAL"

    def __init__(self, start: datetime | None = None):
        self.start = timestamp(start or datetime.now(timezone.utc))
        self._elapsed = 0.0

    @property
    def elapsed_ms(self) -> float:
        return self._elapsed

    def now(self) -> datetime:
        return self.start + timedelta(milliseconds=self._elapsed)

    def restore(self, logical_time_ms: float, *, origin=None) -> None:
        self._elapsed = logical_time_ms
        if origin is not None:
            self.start = timestamp(origin)

    async def wait_ms(self, duration_ms: float) -> None:
        self._elapsed += max(0, duration_ms)
        await asyncio.sleep(0)
