import argparse
import logging
import time

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import get_engine
from app.core.errors import AppError
from app.lab import runner, queries
from app.lab.database import LAB_LOCK, check_database, engine, configure
from app.services import v2_lab

logger = logging.getLogger("app.lab.worker")


def work(runner_id, once=False):
    while True:
        # Dedicated session lock covers recovery, layout changes, all trials and
        # terminal metadata. A second process cannot recover the active runner.
        with engine().connect() as lock:
            check_database(lock)
            acquired = lock.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": LAB_LOCK}
            )
            lock.commit()
            if acquired:
                try:
                    v2_lab.recover_abandoned(runner_id)
                    experiment = v2_lab.claim(runner_id)
                    if experiment:
                        experiment_id = experiment["experiment_id"]
                        logger.info(
                            "experiment_id=%s runner=%s phase=PREPARING",
                            experiment_id,
                            runner_id,
                        )
                        try:
                            try:
                                runner.run(experiment, lock)
                            finally:
                                # The same lock-owning connection performs DDL.
                                # Never reconnect and mutate after losing that lock.
                                if not lock.invalidated:
                                    lock.rollback()
                                    with lock.begin():
                                        configure(lock, experiment["dataset_id"])
                                        if lock.scalar(
                                            text(
                                                "SELECT to_regclass('spans') IS NOT NULL"
                                            )
                                        ):
                                            queries.restore_layout(lock)
                        except AppError as exc:
                            runner.publish_summaries(experiment)
                            status = (
                                "CANCELLED"
                                if exc.code == "EXPERIMENT_CANCELLED"
                                else "FAILED"
                            )
                            v2_lab.finish(experiment_id, runner_id, status, exc.code)
                        except DBAPIError as exc:
                            runner.publish_summaries(experiment)
                            code = (
                                "EXPERIMENT_TIMEOUT"
                                if getattr(exc.orig, "sqlstate", None)
                                in {"57014", "55P03"}
                                else "EXPERIMENT_DATABASE_ERROR"
                            )
                            v2_lab.finish(experiment_id, runner_id, "FAILED", code)
                        except Exception:
                            runner.publish_summaries(experiment)
                            v2_lab.finish(
                                experiment_id,
                                runner_id,
                                "FAILED",
                                "EXPERIMENT_INTERNAL_ERROR",
                            )
                        else:
                            v2_lab.finish(experiment_id, runner_id, "SUCCESS")
                        logger.info(
                            "experiment_id=%s runner=%s phase=FINISHED",
                            experiment_id,
                            runner_id,
                        )
                finally:
                    if not lock.invalidated:
                        lock.rollback()
                        lock.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": LAB_LOCK}
                        )
                        lock.commit()
        if once:
            return
        time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description="Isolated database experiment Worker")
    parser.add_argument("--runner-id", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 1 <= len(args.runner_id) <= 100 or "\x00" in args.runner_id:
        parser.error("runner-id must be 1–100 characters without zero bytes")
    logging.basicConfig(level=logging.INFO)
    try:
        work(args.runner_id, args.once)
    except KeyboardInterrupt:
        pass
    finally:
        get_engine().dispose()
        engine().dispose()


if __name__ == "__main__":
    main()
