"""Structural protocols and JSON helpers. Wire shapes remain owned by contracts/v2."""

from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Protocol
from uuid import UUID


class EngineError(ValueError):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code, self.details = code, details


class ExecutionSink(Protocol):
    async def commit(self, batch: dict) -> dict: ...
    async def control(self) -> dict: ...


class ExecutionContext(Protocol):
    run_id: str
    trace_id: str
    definition: dict
    definition_hash: str
    config: dict
    agent_bindings: dict
    lease_epoch: int
    checkpoint: dict | None
    last_seq: int
    clock: object


def value(obj, key, default=None):
    return (
        obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
    )


def mapping(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    return obj.model_dump(mode="json")


def timestamp(value: str | datetime) -> datetime:
    if not isinstance(value, (str, datetime)):
        raise ValueError("Expected an aware timestamp")
    result = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone is required")
    return result.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return timestamp(value).isoformat().replace("+00:00", "Z")


def encoded(obj) -> bytes:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(obj) -> str:
    """Logical-record digest. HTTP request JCS hashing remains the B adapter's job."""
    return hashlib.sha256(encoded(obj)).hexdigest()


@lru_cache
def schema(name: str) -> dict:
    path = Path(__file__).resolve().parents[3] / "contracts" / "v2" / name
    return json.loads(path.read_text(encoding="utf-8"))


def check_shape(data, spec: dict, *, root=None, path="$") -> None:
    """Validate the keywords used by the frozen schemas, without a runtime dependency.

    B's public validation adapter remains the authoritative HTTP boundary. This
    reader consumes the same checked-in schemas for the independent engine.
    """
    root = spec if root is None else root
    if "$ref" in spec:
        target = root
        for part in spec["$ref"].split("/")[1:]:
            target = target[part]
        return check_shape(data, target, root=root, path=path)
    for union in ("oneOf", "anyOf"):
        if union in spec:
            matches = 0
            for option in spec[union]:
                try:
                    check_shape(data, option, root=root, path=path)
                    matches += 1
                except ValueError:
                    pass
            if not matches or (union == "oneOf" and matches != 1):
                raise ValueError(f"{path}: invalid union value")
    kind = spec.get("type")
    types = {
        "object": dict,
        "array": list,
        "string": str,
        "boolean": bool,
        "null": type(None),
    }
    if kind in types and not isinstance(data, types[kind]):
        raise ValueError(f"{path}: expected {kind}")
    if kind in {"number", "integer"}:
        if type(data) not in (int, float) or not math.isfinite(data):
            raise ValueError(f"{path}: expected finite number")
        if kind == "integer" and int(data) != data:
            raise ValueError(f"{path}: expected integer")
    if "const" in spec and data != spec["const"]:
        raise ValueError(f"{path}: incorrect constant")
    if "enum" in spec and data not in spec["enum"]:
        raise ValueError(f"{path}: unsupported value")
    if isinstance(data, dict):
        if set(spec.get("required", [])) - data.keys():
            raise ValueError(f"{path}: missing required fields")
        properties = spec.get("properties", {})
        for key, item in data.items():
            if "propertyNames" in spec:
                check_shape(key, spec["propertyNames"], root=root, path=path)
            rule = properties.get(key, spec.get("additionalProperties", {}))
            if rule is False:
                raise ValueError(f"{path}.{key}: unknown field")
            if isinstance(rule, dict):
                check_shape(item, rule, root=root, path=f"{path}.{key}")
    if isinstance(data, list):
        if not spec.get("minItems", 0) <= len(data) <= spec.get("maxItems", math.inf):
            raise ValueError(f"{path}: array length out of range")
        for index, item in enumerate(data):
            check_shape(item, spec.get("items", {}), root=root, path=f"{path}[{index}]")
    if isinstance(data, str):
        if "\0" in data or not spec.get("minLength", 0) <= len(data) <= spec.get(
            "maxLength", math.inf
        ):
            raise ValueError(f"{path}: invalid text length or NUL")
        if "pattern" in spec and re.search(spec["pattern"], data) is None:
            raise ValueError(f"{path}: invalid pattern")
        if spec.get("format") == "uuid":
            UUID(data)
        if spec.get("format") == "date-time":
            timestamp(data)
    if type(data) in (int, float):
        if not math.isfinite(data) or not spec.get(
            "minimum", -math.inf
        ) <= data <= spec.get("maximum", math.inf):
            raise ValueError(f"{path}: number out of range")
