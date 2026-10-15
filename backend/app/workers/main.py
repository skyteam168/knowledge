"""Worker entrypoint: `dramatiq app.workers.main`."""

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.workers import (
    analytics,
    broker,
    curation,
    directory,
    evaluation,
    indexing,
    ingest,
    tasks,
)

setup_logging(get_settings().log_level)

__all__ = [
    "analytics",
    "broker",
    "curation",
    "directory",
    "evaluation",
    "indexing",
    "ingest",
    "tasks",
]
