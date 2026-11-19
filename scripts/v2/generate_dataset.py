"""Register and load BENCH clones through B's Loader, or check an offline stream."""

import importlib
from pathlib import Path

from _common import HttpClient, StateFile, parser, run_cli
from _datasets import DatasetChecker, GENERATOR_VERSION, SIZES, iter_dataset
from seed_demo import ensure_resource


def generate(args, summary):
    config = {
        "profile": args.profile,
        "distribution": args.distribution,
        "failure_rate": args.failure_rate,
        "selectivity": args.selectivity,
        "payload_bytes": args.payload_bytes,
    }
    checker = DatasetChecker(seed=args.seed, config=config)
    records = iter_dataset(seed=args.seed, **config)
    summary.update(
        path="OFFLINE_VALIDATION" if args.offline else "ISOLATED_LOADER",
        parameters=config | {"seed": args.seed},
        persisted=False,
    )

    def checked_records():
        for bundle in records:
            checker.consume(bundle)
            yield bundle

    if args.offline:
        for _ in checked_records():
            pass
    else:
        state = StateFile(args.state_file)
        state.bind({"base_url": args.base_url, "seed": args.seed, **config})
        client = HttpClient(args.base_url, state=state)
        dataset = ensure_resource(
            client,
            state,
            "dataset",
            "/datasets",
            {
                "name": args.profile,
                "purpose": "BENCHMARK",
                "seed": args.seed,
                "config": config,
                "generator_version": GENERATOR_VERSION,
            },
        )
        summary["dataset_id"] = dataset["dataset_id"]
        loader = importlib.import_module("app.lab.loader")
        expected_checker = DatasetChecker(seed=args.seed, config=config)
        for bundle in iter_dataset(seed=args.seed, **config):
            expected_checker.consume(bundle)
        expected = expected_checker.summary()
        # Loader consumes an iterator of documented per-Run five-table bundles.
        # It alone owns SQL/COPY, transactions, isolated schema and permissions.
        loader.load_dataset(
            dataset["dataset_id"],
            checked_records(),
            {
                "generator_version": GENERATOR_VERSION,
                "seed": args.seed,
                "config": config,
                "actual_counts": expected["actual_counts"],
                "content_hash": expected["content_hash"],
            },
        )
        result = checker.summary()
        if (
            result["content_hash"] != expected["content_hash"]
            or result["actual_counts"] != expected["actual_counts"]
        ):
            raise ValueError("Loader did not consume the complete deterministic stream")
        finalized = client.request(
            "POST",
            f"/datasets/{dataset['dataset_id']}/finalize",
            {
                "actual_counts": result["actual_counts"],
                "content_hash": result["content_hash"],
            },
        )
        if finalized["state"] != "READY":
            raise ValueError("Dataset was not finalized READY")
        summary["persisted"] = True
    summary.update(checker.summary())


def main(argv=None):
    cli = parser(__doc__)
    cli.add_argument("--profile", choices=list(SIZES), default="BENCH_1M")
    cli.add_argument("--seed", type=int, default=42)
    cli.add_argument(
        "--distribution", choices=["uniform", "hotspot"], default="uniform"
    )
    cli.add_argument(
        "--failure-rate", type=float, choices=[0.01, 0.1, 0.5], default=0.1
    )
    cli.add_argument(
        "--selectivity", type=float, choices=[0.001, 0.01, 0.1, 0.5], default=0.01
    )
    cli.add_argument(
        "--payload-bytes", type=int, choices=[128, 1024, 4096], default=128
    )
    cli.add_argument(
        "--offline",
        action="store_true",
        help="Validate the full generated stream without claiming persistence",
    )
    cli.add_argument(
        "--state-file", default=str(Path("backend/var/v2/dataset-state.json"))
    )
    return run_cli(generate, cli.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
