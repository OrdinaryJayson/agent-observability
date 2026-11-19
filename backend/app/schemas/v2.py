from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.v2 import StrictModel, WorkflowDefinition
from app.schemas.text import DatabaseText
from app.schemas.v1 import TimeWindow


class WorkflowCreate(StrictModel):
    name: DatabaseText = Field(min_length=1, max_length=100, pattern=r"\S")
    description: DatabaseText | None = None
    draft: WorkflowDefinition


class WorkflowPatch(StrictModel):
    name: DatabaseText = Field(
        default=None, min_length=1, max_length=100, pattern=r"\S"
    )
    description: DatabaseText | None = None
    draft: WorkflowDefinition = None
    archived: bool = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("An update is required")
        return self


class DraftValidation(StrictModel):
    draft: WorkflowDefinition


class Publish(StrictModel):
    expected_definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Empty(StrictModel):
    pass


class CursorQuery(StrictModel):
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=4096)


class WindowQuery(TimeWindow):
    mode: Literal["REALTIME", "VIRTUAL", "LEGACY"] = "REALTIME"


class RunQuery(CursorQuery, TimeWindow):
    mode: Literal["REALTIME", "VIRTUAL", "LEGACY"] | None = None
    task_id: UUID | None = None
    version_id: UUID | None = None
    status: Literal["RUNNING", "SUCCESS", "FAILED", "CANCELLED"] | None = None
    execution_state: (
        Literal["QUEUED", "RUNNING", "RECOVERING", "FINALIZING", "FINISHED"] | None
    ) = None


class JournalQuery(StrictModel):
    after_seq: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=100)


class StreamQuery(StrictModel):
    after_seq: int | None = Field(default=None, ge=0)


class Compare(StrictModel):
    run_ids: list[UUID] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("Run IDs must be distinct")
        return self


class SeriesQuery(WindowQuery):
    metric: Literal["RUNS", "TOKENS"] = "RUNS"
    granularity: Literal["DAY"] = "DAY"

    @model_validator(mode="after")
    def bounded_window(self):
        if (
            self.from_time is None
            or self.to_time is None
            or (self.to_time - self.from_time).total_seconds() > 366 * 86400
        ):
            raise ValueError("A window of at most 366 days is required")
        from datetime import timedelta

        if (
            (self.to_time - timedelta(microseconds=1)).date() - self.from_time.date()
        ).days >= 366:
            raise ValueError("At most 366 UTC dates are supported")
        return self
