from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class OutboxEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any]
    status: str
    retry_count: int
    last_error: str | None
    created_at: datetime
    processed_at: datetime | None
    next_attempt_at: datetime | None
    locked_until: datetime | None


class OutboxStatsOut(BaseModel):
    pending: int = 0
    processing: int = 0
    done: int = 0
    dead: int = 0


class RetryResultOut(BaseModel):
    count: int


class IndexGenerationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    qdrant_collection: str
    opensearch_index: str
    embedding_model: str
    embedding_dim: int
    status: str
    stats: dict[str, Any]
    error: str | None
    created_at: datetime
    activated_at: datetime | None
    retired_at: datetime | None


class BackendDiffOut(BaseModel):
    count: int
    missing_count: int
    extra_count: int
    # Samples (at most `sample_limit` ids each).
    missing: list[str]
    extra: list[str]


class ConsistencyReportOut(BaseModel):
    kb_id: str
    generation: int
    checked_at: datetime
    consistent: bool
    pg_count: int
    qdrant: BackendDiffOut
    opensearch: BackendDiffOut
    reindex_documents: list[str]
    skipped_documents: int


class RepairQueuedOut(BaseModel):
    queued: bool
    kb_id: str
