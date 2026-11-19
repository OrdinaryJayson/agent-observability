import copy

import pytest
from pydantic import ValidationError

from app.contracts.v2 import JournalBatch, RunStart, WorkflowDefinition, digest


def test_frozen_schemas_and_jcs(samples):
    for definition in samples["workflow_definitions"].values():
        assert WorkflowDefinition.model_validate(definition).root == definition
    for batch in samples["journal_batches"]:
        assert JournalBatch.model_validate(batch).root == batch
    assert digest({"b": 1.0, "a": [2]}) == digest({"a": [2], "b": 1})
    assert digest({"x": 0.0}) == digest({"x": -0.0})
    for value in (float("nan"), float("inf"), "\x00", "\ud800"):
        with pytest.raises((ValueError, UnicodeError)):
            digest({"value": value})


def test_budget_time_and_unknown_fields(samples):
    batch = copy.deepcopy(samples["journal_batches"][0])
    batch["events"][0]["occurred_at"] = "2026-01-01T00:00:00"
    with pytest.raises(ValidationError):
        JournalBatch.model_validate(batch)
    batch = copy.deepcopy(samples["journal_batches"][0])
    batch["events"][0]["payload"]["attributes"] = {"oversize": "x" * (512 * 1024)}
    with pytest.raises(ValidationError):
        JournalBatch.model_validate(batch)
    body = {**samples["run_start"], "seed": True}
    with pytest.raises(ValidationError):
        RunStart.model_validate(body)


def test_openapi_contains_the_frozen_workflow_shape():
    from app.main import app

    schema = app.openapi()["components"]["schemas"]["WorkflowDefinition"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["nodes"]["maxItems"] == 50
    assert "schema_version" in schema["required"]


def test_http_manifest_routes_are_registered():
    import json
    from pathlib import Path
    from app.main import app

    manifest = json.loads(
        (
            Path(__file__).resolve().parents[3] / "contracts/v2/http-manifest.json"
        ).read_text(encoding="utf-8")
    )
    paths = app.openapi()["paths"]
    for route in manifest["routes"]:
        assert route["method"].lower() in paths[route["path"]]


def test_live_span_shape_and_token_rules(samples):
    from app.contracts.v2 import LiveSpan

    for name in ("snapshot", "running_snapshot"):
        for span in samples[name]["spans"]:
            LiveSpan.model_validate(span)
    value = copy.deepcopy(samples["running_snapshot"]["spans"][0])
    value["input_tokens"] = 1
    with pytest.raises(ValidationError):
        LiveSpan.model_validate(value)
