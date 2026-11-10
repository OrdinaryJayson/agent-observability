"""Frozen shared types owned by the project lead, with no business imports."""

from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field

TraceId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
SpanId = Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
