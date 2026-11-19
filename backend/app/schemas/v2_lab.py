from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.contracts.v2 import StrictModel
from app.schemas.text import DatabaseText
from app.schemas.v2 import CursorQuery

Selectivity = Literal[0.001, 0.01, 0.1, 0.5]


class DatasetCreate(StrictModel):
    name: DatabaseText = Field(min_length=1, max_length=100, pattern=r"\S")
    purpose: Literal["DEMO", "BENCHMARK", "LOAD"]
    seed: int = Field(ge=-2147483648, le=2147483647)
    config: dict
    generator_version: DatabaseText = Field(min_length=1, max_length=80)


class DatasetFinalize(StrictModel):
    actual_counts: dict[str, int]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class IndexParameters(StrictModel):
    query: Literal["TRACE", "ERROR"]
    selectivity: Selectivity


class JsonParameters(StrictModel):
    selectivity: Selectivity


class PaginationParameters(StrictModel):
    rank: Literal[0, 10000, 100000]
    limit: Literal[50]


class AggregateParameters(StrictModel):
    window_days: Literal[1, 7, 30, 90]


class MvccParameters(StrictModel):
    schedule: Literal["NON_REPEATABLE_READ", "WRITE_SKEW"]


class QueueParameters(StrictModel):
    claimers: Literal[1, 2, 4, 8]
    jobs: Literal[1000]


class ExperimentBase(StrictModel):
    dataset_id: UUID
    seed: int = Field(default=42, ge=-2147483648, le=2147483647)
    warmups: Literal[3] = 3
    repetitions: Literal[15, 30] = 15


class IndexExperiment(ExperimentBase):
    case_code: Literal["INDEX_SELECTIVITY"]
    parameters: IndexParameters


class JsonExperiment(ExperimentBase):
    case_code: Literal["JSONB_GIN"]
    parameters: JsonParameters


class PaginationExperiment(ExperimentBase):
    case_code: Literal["PAGINATION"]
    parameters: PaginationParameters


class AggregateExperiment(ExperimentBase):
    case_code: Literal["AGGREGATION"]
    parameters: AggregateParameters


class MvccExperiment(ExperimentBase):
    case_code: Literal["MVCC_ISOLATION"]
    parameters: MvccParameters


class QueueExperiment(ExperimentBase):
    case_code: Literal["QUEUE_CONTENTION"]
    parameters: QueueParameters


ExperimentRequest = Annotated[
    IndexExperiment
    | JsonExperiment
    | PaginationExperiment
    | AggregateExperiment
    | MvccExperiment
    | QueueExperiment,
    Field(discriminator="case_code"),
]


class SampleQuery(CursorQuery):
    trial_id: UUID


class ExportQuery(StrictModel):
    format: Literal["json", "csv"] = "json"
