"""Frozen execution input; database existence/ACTIVE validation belongs to B."""

from typing import Literal
from uuid import UUID
from pydantic import Field, model_validator
from app.contracts.base import StrictModel


class SimulationConfig(StrictModel):
    scenario: Literal["research"] = "research"
    agent_count: int = Field(default=3, ge=1, le=3)
    min_spans: int = Field(default=8, ge=1, le=500)
    max_spans: int = Field(default=20, ge=1, le=500)
    failure_rate: float = Field(default=0.1, ge=0, le=1)
    seed: int = 42
    agent_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.min_spans > self.max_spans:
            raise ValueError("min_spans must not exceed max_spans")
        if self.agent_ids is not None:
            if len(self.agent_ids) != self.agent_count:
                raise ValueError("agent_ids length must equal agent_count")
            if len(set(self.agent_ids)) != len(self.agent_ids):
                raise ValueError("agent_ids must be unique")
        return self
