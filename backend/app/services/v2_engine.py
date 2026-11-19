"""Late-bound C interfaces: B never substitutes its own execution algorithm."""

import importlib

from app.core.errors import AppError
from app.contracts.v2 import ClosedProjection, SnapshotProjection, ValidationReport


def function(name):
    package = (
        "app.analysis_v2"
        if name in {"analyze_run", "compare_runs"}
        else "app.execution_v2"
    )
    try:
        return getattr(importlib.import_module(package), name)
    except (ImportError, AttributeError) as exc:
        raise AppError(
            409, "FEATURE_NOT_AVAILABLE", f"C interface {name} is unavailable"
        ) from exc


def plain(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def validate_workflow(definition):
    return ValidationReport.model_validate(
        plain(function("validate_workflow")(definition))
    ).model_dump(mode="json")


def reduce_journal(events):
    return SnapshotProjection.model_validate(
        plain(function("reduce_journal")(events=events))
    ).model_dump(mode="json")


def seal_interrupted(events, reason, ended_at):
    return ClosedProjection.model_validate(
        plain(
            function("seal_interrupted")(
                events=events, reason=reason, ended_at=ended_at
            )
        )
    ).model_dump(mode="json")
