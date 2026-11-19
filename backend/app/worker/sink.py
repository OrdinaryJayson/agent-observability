import asyncio
import copy
from uuid import UUID

from app.contracts.v2 import BatchAck, ControlState, JournalBatch
from app.core.database import get_engine
from app.core.errors import AppError
from app.repositories.v2 import journal
from app.services import v2_journal, v2_runs


class PersistentSink:
    def __init__(self, run_id, worker_id, epoch):
        self.run_id, self.worker_id, self.epoch = run_id, worker_id, epoch
        self.cached = None
        self.lock = asyncio.Lock()

    async def refresh(self, renew=False):
        state = await asyncio.to_thread(
            v2_runs.control, self.run_id, self.worker_id, self.epoch, renew
        )
        self.cached = ControlState(**state)
        return self.cached

    async def control(self):
        return self.cached or await self.refresh()

    async def commit(self, batch):
        value = copy.deepcopy(JournalBatch.model_validate(batch).root)
        if UUID(value["run_id"]) != UUID(str(self.run_id)):
            raise AppError(422, "VALIDATION_ERROR", "Batch belongs to a different Run")
        async with self.lock:
            for attempt in range(3):
                try:
                    result = await asyncio.to_thread(
                        v2_journal.commit, self.worker_id, value
                    )
                    return BatchAck(**result)
                except AppError as exc:
                    if exc.code != "CHECKPOINT_CONFLICT" or attempt == 2:
                        raise

                    def controls_only():
                        with get_engine().connect() as conn:
                            events = journal(
                                conn, self.run_id, value["expected_last_seq"]
                            )
                            return events and all(
                                e["kind"]
                                in {"cancel.requested", "run.recovering", "run.started"}
                                for e in events
                            )

                    if not await asyncio.to_thread(controls_only):
                        raise
                    value["expected_last_seq"] = exc.details["last_seq"]
                    value["checkpoint"]["journal_seq"] = exc.details["last_seq"]
