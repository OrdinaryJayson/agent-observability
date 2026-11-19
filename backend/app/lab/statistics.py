"""Type-7 summaries of stored samples; C owns the cross-experiment report."""

import random
import statistics


def quantile(values, p):
    values = sorted(values)
    h = (len(values) - 1) * p
    low = int(h)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (h - low)


def summarize(samples, baseline, seed):
    measured = [s for s in samples if not s["is_warmup"]]
    valid = [
        s
        for s in measured
        if s["correctness"]["passed"] and s["metrics"].get("client_ms") is not None
    ]
    values = [s["metrics"]["client_ms"] for s in valid]
    result = {
        "n": len(values),
        "median_ms": None,
        "p95_ms": None,
        "iqr_ms": None,
        "paired_difference_ms": None,
        "bootstrap_ci95_ms": None,
        "failed_samples": sum(not s["correctness"]["passed"] for s in samples),
    }
    if not values:
        return result
    result.update(
        median_ms=statistics.median(values),
        p95_ms=quantile(values, 0.95),
        iqr_ms=quantile(values, 0.75) - quantile(values, 0.25),
    )
    before = {
        s["repetition"]: s["metrics"]["client_ms"]
        for s in baseline
        if not s["is_warmup"]
        and s["correctness"]["passed"]
        and s["metrics"].get("client_ms") is not None
    }
    differences = [
        s["metrics"]["client_ms"] - before[s["repetition"]]
        for s in valid
        if s["repetition"] in before
    ]
    if differences:
        rng = random.Random(seed)
        bootstrap = [
            statistics.median(rng.choices(differences, k=len(differences)))
            for _ in range(1000)
        ]
        result.update(
            paired_difference_ms=statistics.median(differences),
            bootstrap_ci95_ms=[quantile(bootstrap, 0.025), quantile(bootstrap, 0.975)],
        )
    return result
