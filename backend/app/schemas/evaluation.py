from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ImportSource = Literal["feedback", "gap"]


def _clean_ids(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


class EvalDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class EvalDatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class EvalDatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    case_count: int = 0
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class EvalCaseBase(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    reference_answer: str | None = Field(default=None, max_length=20000)
    expected_document_ids: list[str] = Field(default_factory=list, max_length=50)
    expected_chunk_ids: list[str] = Field(default_factory=list, max_length=200)
    kb_ids: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("expected_document_ids", "expected_chunk_ids", "kb_ids", "tags")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return _clean_ids(value)


class EvalCaseCreate(EvalCaseBase):
    pass


class EvalCaseUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    reference_answer: str | None = Field(default=None, max_length=20000)
    expected_document_ids: list[str] | None = Field(default=None, max_length=50)
    expected_chunk_ids: list[str] | None = Field(default=None, max_length=200)
    kb_ids: list[str] | None = Field(default=None, max_length=50)
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("expected_document_ids", "expected_chunk_ids", "kb_ids", "tags")
    @classmethod
    def _dedupe(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_ids(value)


class EvalCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    question: str
    reference_answer: str | None
    expected_document_ids: list[str]
    expected_chunk_ids: list[str]
    kb_ids: list[str]
    tags: list[str]
    source: str
    source_id: str | None
    created_at: datetime
    updated_at: datetime


class EvalCandidateOut(BaseModel):
    """An upvoted answer or a resolved gap that can be turned into an evaluation case."""

    source: ImportSource
    source_id: str
    question: str
    reference_answer: str | None
    expected_document_ids: list[str]
    expected_chunk_ids: list[str]
    kb_ids: list[str]
    created_at: datetime
    imported: bool = False


class EvalImportIn(BaseModel):
    source: ImportSource
    source_ids: list[str] = Field(min_length=1, max_length=500)


class EvalImportOut(BaseModel):
    created: int
    skipped: int


class EvalRunCreate(BaseModel):
    dataset_id: str
    # Retrieval profile id, or "builtin".
    profile_id: str = "builtin"
    name: str | None = Field(default=None, max_length=128)
    # Generate answers and score them with the LLM judge (slower, costs model calls).
    judge_enabled: bool = True


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    dataset_name: str = ""
    name: str | None
    profile_id: str | None
    profile_name: str
    config: dict[str, Any]
    environment: dict[str, Any]
    judge_enabled: bool
    status: str
    case_count: int
    done_count: int
    metrics: dict[str, Any]
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_by: str | None
    created_at: datetime


class EvalResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    case_id: str
    question: str = ""
    reference_answer: str | None = None
    expected_document_ids: list[str] = Field(default_factory=list)
    retrieved: list[dict[str, Any]]
    metrics: dict[str, Any]
    answer: str | None
    citations: list[dict[str, Any]]
    grounding: str | None
    judge: dict[str, Any]
    latency_ms: int
    error: str | None


class EvalCompareCaseOut(BaseModel):
    case_id: str
    question: str
    # run id -> metrics of that run's result for the case.
    metrics: dict[str, dict[str, Any]]


class EvalConfigDiffOut(BaseModel):
    key: str
    # run id -> value
    values: dict[str, Any]


class EvalCompareOut(BaseModel):
    runs: list[EvalRunOut]
    metric_keys: list[str]
    config_diff: list[EvalConfigDiffOut]
    cases: list[EvalCompareCaseOut]
