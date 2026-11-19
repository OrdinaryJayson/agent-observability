"""Frozen v2 validation adapters; no database or business imports.

The repository's JSON Schemas remain the source of structural truth. These
Pydantic adapters retain JSON dictionaries for C's independent Protocol API.
"""

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    model_validator,
)

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts/v2"


def safe_json(value):
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("Zero bytes are not supported")
        value.encode("utf-8")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Numbers must be finite")
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON keys must be strings")
            safe_json(key)
            safe_json(item)
    elif isinstance(value, list):
        for item in value:
            safe_json(item)
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ValueError("Expected JSON data")
    return value


def canonical(value) -> bytes:
    return rfc8785.dumps(safe_json(value))


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def utc(value: str) -> datetime:
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.utcoffset() is None:
        raise ValueError("A timezone is required")
    try:
        return value.astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError("UTC time out of range") from exc


@lru_cache
def schema_validator(name):
    schema = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


class SchemaDocument(RootModel[dict]):
    schema_file: ClassVar[str]

    @model_validator(mode="after")
    def validate_document(self):
        safe_json(self.root)
        errors = list(schema_validator(self.schema_file).iter_errors(self.root))
        if errors:
            error = errors[0]
            raise ValueError(f"Invalid {self.schema_file} at {list(error.path)}")
        return self

    @classmethod
    def model_json_schema(cls, **kwargs):
        return schema_validator(cls.schema_file).schema

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = copy.deepcopy(schema_validator(cls.schema_file).schema)

        def inline(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    return inline(schema["$defs"][value["$ref"].split("/")[-1]])
                return {
                    k: inline(v)
                    for k, v in value.items()
                    if k not in {"$defs", "$id", "$schema"}
                }
            if isinstance(value, list):
                return [inline(v) for v in value]
            return value

        return inline(schema)


class WorkflowDefinition(SchemaDocument):
    schema_file = "workflow.schema.json"


class JournalBatch(SchemaDocument):
    schema_file = "journal-batch.schema.json"

    @model_validator(mode="after")
    def budgets_and_times(self):
        data = self.root
        if len(json.dumps(data, ensure_ascii=False).encode()) > 512 * 1024:
            raise ValueError("Batch exceeds 512 KiB")
        if (
            len(json.dumps(data["checkpoint"], ensure_ascii=False).encode())
            > 256 * 1024
        ):
            raise ValueError("Checkpoint exceeds 256 KiB")
        ids = [event["producer_event_id"] for event in data["events"]]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate producer event ID")
        for event in data["events"]:
            utc(event["occurred_at"])
            for key in ("start_time", "end_time", "occurred_at"):
                if key in event["payload"]:
                    utc(event["payload"][key])
        return self


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="after")
    def json_values(self):
        safe_json(self.model_dump(mode="json", exclude_unset=True))
        return self


class BatchAck(StrictModel):
    run_id: UUID
    batch_id: UUID
    first_seq: int = Field(ge=1)
    last_seq: int = Field(ge=1)
    duplicate: bool
    terminal_committed: bool


class ControlState(StrictModel):
    cancel_requested: bool
    lease_valid: bool
    deadline_at: AwareDatetime
    last_seq: int = Field(ge=0)


class ExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    run_id: UUID
    trace_id: str
    definition: dict
    definition_hash: str
    config: dict
    agent_bindings: dict
    lease_epoch: int
    checkpoint: dict
    last_seq: int
    clock: Any


class ExecutionSink(Protocol):
    async def commit(self, batch: JournalBatch) -> BatchAck: ...
    async def control(self) -> ControlState: ...


class RunStart(StrictModel):
    version_id: UUID
    agent_bindings: dict[str, UUID]
    unbound: bool = False
    seed: int = Field(default=42, ge=-2147483648, le=2147483647, strict=True)
    mode: Literal["REALTIME", "VIRTUAL"] = "REALTIME"
    max_parallelism: int = Field(default=4, ge=1, le=4, strict=True)
    priority: int = Field(default=0, ge=-10, le=10, strict=True)
    retry_of_run_id: UUID | None = None
    dataset_id: UUID | None = None


# Re-export the prose-defined shapes after StrictModel is initialized.
from app.contracts.v2.projections import (  # noqa: E402,F401
    ClosedProjection,
    Link,
    LiveSpan,
    NodeState,
    SnapshotProjection,
    SpanOpen,
    ValidationIssue,
    ValidationReport,
)
