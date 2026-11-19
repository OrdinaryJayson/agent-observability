import argparse
import asyncio
import importlib
import logging
import time


from app.core.database import get_engine
from app.repositories.v2 import one
from app.services import v2_engine, v2_runs
from app.worker.recovery import recover_one
from app.worker.sink import PersistentSink

logger = logging.getLogger("app.worker")


def context(owned):
    with get_engine().connect() as conn:
        version = one(
            conn,
            "SELECT definition,definition_hash FROM workflow_versions WHERE version_id=:id",
            id=owned["version_id"],
        )
        run = one(
            conn, "SELECT trace_id FROM runs WHERE run_id=:id", id=owned["run_id"]
        )
    # C owns clock implementations. No simulated timing is implemented by B.
    module = importlib.import_module("app.execution_v2")
    clock_type = getattr(
        module,
        "VirtualClock" if owned["config"]["mode"] == "VIRTUAL" else "RealtimeClock",
    )
    return {
        "run_id": str(owned["run_id"]),
        "trace_id": run["trace_id"],
        **version,
        "config": owned["config"],
        "agent_bindings": owned["agent_bindings"],
        "lease_epoch": owned["lease_epoch"],
        "checkpoint": owned["checkpoint"],
        "last_seq": owned["last_seq"],
        "clock": clock_type(),
    }


async def execute(owned, worker_id):
    sink = PersistentSink(owned["run_id"], worker_id, owned["lease_epoch"])
    await sink.refresh()
    stopped = asyncio.Event()

    async def monitor():
        heartbeat = time.monotonic()
        while not stopped.is_set():
            try:
                renew = time.monotonic() - heartbeat >= 5
                control = await sink.refresh(renew)
                if renew:
                    heartbeat = time.monotonic()
                if not control.lease_valid:
                    return
            except Exception:
                if sink.cached is not None:
                    sink.cached = sink.cached.model_copy(update={"lease_valid": False})
                return
            try:
                await asyncio.wait_for(stopped.wait(), 0.5)
            except TimeoutError:
                pass

    watcher = asyncio.create_task(monitor())
    execution = asyncio.create_task(
        v2_engine.function("execute_workflow")(
            context=await asyncio.to_thread(context, owned), sink=sink
        )
    )
    try:
        done, _ = await asyncio.wait(
            {watcher, execution}, return_when=asyncio.FIRST_COMPLETED
        )
        if execution in done:
            await execution
        else:
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
    finally:
        stopped.set()
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
        await watcher


async def work(worker_id, once=False):
    v2_engine.function("execute_workflow")  # Fail before taking a lease if C is absent.
    while True:
        owned = await asyncio.to_thread(recover_one, worker_id)
        if owned is None:
            owned = await asyncio.to_thread(v2_runs.claim, worker_id)
        if owned and not owned.get("finished"):
            logger.info(
                "run_id=%s epoch=%s phase=execute",
                owned["run_id"],
                owned["lease_epoch"],
            )
            try:
                await execute(owned, worker_id)
            except Exception:
                # Recovery follows lease expiration. Do not log SQL/credentials.
                logger.error(
                    "run_id=%s epoch=%s phase=interrupted",
                    owned["run_id"],
                    owned["lease_epoch"],
                )
        if once:
            return
        if owned is None:
            await asyncio.sleep(0.25)


def main():
    parser = argparse.ArgumentParser(description="Persistent v2 queue Worker")
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 1 <= len(args.worker_id) <= 100 or "\x00" in args.worker_id:
        parser.error("worker-id must be 1–100 characters without zero bytes")
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(work(args.worker_id, args.once))
    except KeyboardInterrupt:
        pass
    finally:
        get_engine().dispose()


if __name__ == "__main__":
    main()
