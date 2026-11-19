"""Rebuild statistics, raw exports and measured charts from v2 experiment exports."""

import csv
import json
import math
from pathlib import Path
import platform
import random
from statistics import median

from _common import ToolError, parser, run_cli

CASES = (
    "INDEX_SELECTIVITY",
    "JSONB_GIN",
    "PAGINATION",
    "AGGREGATION",
    "MVCC_ISOLATION",
    "QUEUE_CONTENTION",
)


def quantile(values, probability):
    if not values:
        return None
    if not 0 <= probability <= 1:
        raise ValueError("Quantile probability must be in [0,1]")
    values = sorted(values)
    if any(
        type(item) not in (int, float) or not math.isfinite(item) for item in values
    ):
        raise ValueError("Non-finite measurement")
    position = (len(values) - 1) * probability
    left = math.floor(position)
    right = math.ceil(position)
    return values[left] + (values[right] - values[left]) * (position - left)


def paired_bootstrap(reference, variant, *, seed=42):
    repetitions = sorted(reference.keys() & variant.keys())
    if not repetitions:
        return None, None
    differences = [variant[index] - reference[index] for index in repetitions]
    rng = random.Random(seed)
    bootstraps = [
        median(rng.choices(differences, k=len(differences))) for _ in range(1000)
    ]
    return median(differences), [
        quantile(bootstraps, 0.025),
        quantile(bootstraps, 0.975),
    ]


def summarize(samples, reference=None, *, seed=42):
    measured = [sample for sample in samples if not sample["is_warmup"]]
    failures = [
        sample
        for sample in measured
        if not sample["correctness"]["passed"]
        or sample["metrics"].get("execution_ms") is None
    ]
    observations = {}
    for sample in measured:
        number = sample["metrics"].get("execution_ms")
        if number is not None and (
            type(number) not in (int, float) or not math.isfinite(number) or number < 0
        ):
            raise ValueError("Invalid execution_ms")
        if sample["repetition"] in observations:
            raise ValueError("Duplicate repetition")
        if sample not in failures:
            observations[sample["repetition"]] = number
    values = list(observations.values())
    difference, ci = (
        paired_bootstrap(reference, observations, seed=seed)
        if reference is not None
        else (None, None)
    )
    return {
        "n": len(values),
        "median_ms": median(values) if values else None,
        "p95_ms": quantile(values, 0.95),
        "iqr_ms": quantile(values, 0.75) - quantile(values, 0.25) if values else None,
        "paired_difference_ms": difference,
        "bootstrap_ci95_ms": ci,
        "failed_samples": len(failures),
    }, observations


def reject_sensitive(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {
                "password",
                "api_key",
                "authorization",
                "database_url",
                "connection_string",
                "dsn",
            }:
                raise ToolError(
                    f"Export contains a sensitive field ({key}). Supply a redacted export."
                )
            reject_sensitive(item)
    elif isinstance(value, list):
        for item in value:
            reject_sensitive(item)
    elif isinstance(value, str) and (
        "postgresql://" in value or "postgresql+psycopg://" in value
    ):
        raise ToolError("Export contains a database connection string")


def _invalid_json_constant(number):
    raise ValueError(f"Non-finite JSON {number}")


def build_report(args, summary):
    paths = sorted(args.input.glob("*.json"))
    if not paths:
        raise ToolError("No experiment export JSON files were found")
    exports, rows, environments, raw_samples = [], [], [], []
    for path in paths:
        if path.stat().st_size > 50 * 1024 * 1024:
            raise ToolError("Export exceeds 50MiB. Use paginated source files.")
        document = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_invalid_json_constant,
        )
        reject_sensitive(document)
        if document.get("note", "").lower().find("synthetic") >= 0:
            raise ToolError(
                "Synthetic protocol fixtures cannot be reported as performance measurements"
            )
        if set(("experiment", "trials", "samples")) - document.keys():
            raise ToolError("Expected a complete experiment export")
        experiment = document["experiment"]
        case = experiment["case_code"]
        if case not in CASES:
            raise ToolError("Unknown experiment case")
        environments.append(experiment["environment"])
        exports.append(document)
        raw_samples.extend(document["samples"])
        reference = None
        for trial in sorted(document["trials"], key=lambda item: item["ordinal"]):
            samples = [
                sample
                for sample in document["samples"]
                if sample["trial_id"] == trial["trial_id"]
            ]
            if any(
                sample["metrics"].get("extra", {}).get("synthetic")
                for sample in samples
            ):
                raise ToolError(
                    "Synthetic fixture metrics cannot be performance evidence"
                )
            seen = [(sample["repetition"], sample["is_warmup"]) for sample in samples]
            if len(set(seen)) != len(seen):
                raise ToolError("Duplicate trial/repetition sample")
            metrics, observations = summarize(samples, reference, seed=args.seed)
            if reference is None:
                reference = observations
            row = {
                "source": path.name,
                "experiment_id": experiment["experiment_id"],
                "case_code": case,
                "dataset_id": experiment.get("dataset_id"),
                "dataset_size": document.get("dataset", {})
                .get("actual_counts", {})
                .get("spans"),
                "variant": trial["variant"],
                "parameters": trial["parameters"],
                **metrics,
                "warmups": sum(sample["is_warmup"] for sample in samples),
                "correctness_passed": all(
                    sample["correctness"]["passed"] for sample in samples
                ),
                "index_bytes": _metric_median(samples, "index_bytes"),
                "insert_ms": _metric_median(samples, "insert_ms"),
            }
            rows.append(row)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "exports.json").write_text(
        json.dumps(exports, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    with (args.output / "results.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(item, sort_keys=True)
                    if isinstance(item, (dict, list))
                    else item
                    for key, item in row.items()
                }
            )
    correctness = {
        "passed": all(row["correctness_passed"] for row in rows),
        "failed_samples": sum(row["failed_samples"] for row in rows),
        "measured_cases": sorted({row["case_code"] for row in rows}),
        "unexecuted_cases": sorted(set(CASES) - {row["case_code"] for row in rows}),
        "incomplete_trials": [
            row["variant"]
            for row in rows
            if row["warmups"] != 3 or row["n"] not in {15, 30}
        ],
    }
    (args.output / "correctness.json").write_text(
        json.dumps(correctness, indent=2), encoding="utf-8"
    )
    (args.output / "environment.json").write_text(
        json.dumps(
            {
                "source_environments": environments,
                "report_host": platform.platform(),
                "statistics_version": "2.0",
                "seed": args.seed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (args.output / "methods.md").write_text(
        "# Measurement methods\n\nSource exports retain all raw samples, plans and correctness checks. "
        "Three warmups are excluded from the 15/30 measured repetitions. Failures/timeouts remain in raw data and are counted separately. "
        "Median, type-7 P95 and IQR use every successful finite measurement. P95 with 15 samples has an unstable tail estimate. "
        "Paired differences are variant minus the first ordinal reference, paired by repetition. "
        f"CI uses 1000 paired bootstrap resamples with seed {args.seed}. "
        "Warm-cache is the default. Client latency and instrumented EXPLAIN execution times remain distinct in source metrics. "
        "Database visibility, plan choice, space and write cost constrain conclusions. Missing combinations have no inferred result.\n",
        encoding="utf-8",
    )
    lines = [
        "# Experiment report",
        "",
        f"Measured cases include {', '.join(correctness['measured_cases'])}.",
        "",
        "| Case | Size | Variant | n | Median ms | P95 ms | IQR ms | Paired difference ms | CI95 ms | Index bytes | Insert ms |",
        "|---|---:|---|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                str(row[key])
                for key in (
                    "case_code",
                    "dataset_size",
                    "variant",
                    "n",
                    "median_ms",
                    "p95_ms",
                    "iqr_ms",
                    "paired_difference_ms",
                    "bootstrap_ci95_ms",
                    "index_bytes",
                    "insert_ms",
                )
            )
            + " |"
        )
    lines += [
        "",
        "Raw exports and plans are in exports.json. All failed samples remain recorded.",
        "",
        "Unexecuted cases: " + ", ".join(correctness["unexecuted_cases"]),
        "",
        "Interpretation requires matching dataset, parameters, isolation and environment. Faster incorrect results fail correctness checks.",
    ]
    (args.output / "experiment-report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    _plots(rows, args.output)
    summary.update(
        actual_samples=len(raw_samples),
        trials=len(rows),
        correctness=correctness,
        output=str(args.output),
    )
    if not correctness["passed"] or correctness["incomplete_trials"]:
        raise ToolError(
            "Report includes failed correctness checks or incomplete trials"
        )


def _metric_median(samples, key):
    values = [
        sample["metrics"][key]
        for sample in samples
        if not sample["is_warmup"] and sample["metrics"].get(key) is not None
    ]
    return median(values) if values else None


def _plots(rows, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = {
        "INDEX_SELECTIVITY": "selectivity",
        "JSONB_GIN": "selectivity",
        "PAGINATION": "rank",
        "AGGREGATION": "window_days",
        "QUEUE_CONTENTION": "claimers",
    }
    for case, parameter in groups.items():
        selected = [
            row
            for row in rows
            if row["case_code"] == case and row["median_ms"] is not None
        ]
        if not selected:
            continue
        figure, axis = plt.subplots(figsize=(8, 4))
        labels = {(row["variant"], row["dataset_size"]) for row in selected}
        for variant, size in sorted(labels, key=str):
            points = sorted(
                (row["parameters"][parameter], row["median_ms"])
                for row in selected
                if row["variant"] == variant and row["dataset_size"] == size
            )
            axis.plot(
                [point[0] for point in points],
                [point[1] for point in points],
                marker="o",
                label=f"{variant}, {size} spans",
            )
        axis.set_xlabel(parameter)
        axis.set_ylabel("Median execution time (ms)")
        axis.legend(fontsize=8)
        axis.grid(alpha=0.2)
        figure.tight_layout()
        figure.savefig(output / f"{case.lower()}.svg")
        figure.savefig(output / f"{case.lower()}.png", dpi=140)
        plt.close(figure)


def main(argv=None):
    cli = parser(__doc__)
    cli.add_argument("--input", type=Path, required=True)
    cli.add_argument("--output", type=Path, default=Path("reports/v2"))
    cli.add_argument("--seed", type=int, default=42)
    return run_cli(build_report, cli.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
