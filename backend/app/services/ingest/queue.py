from dataclasses import dataclass, field
from typing import Protocol


class TaskQueue(Protocol):
    def enqueue_parse(self, document_id: str, version: int) -> None: ...
    def enqueue_chunk(self, document_id: str, version: int) -> None: ...
    def enqueue_index_repair(self, org_id: str, kb_id: str) -> None: ...
    def enqueue_eval_run(self, run_id: str) -> None: ...
    def enqueue_directory_sync(self, run_id: str) -> None: ...


class DramatiqTaskQueue:
    def enqueue_parse(self, document_id: str, version: int) -> None:
        from app.workers.ingest import parse_document

        parse_document.send(document_id, version)

    def enqueue_chunk(self, document_id: str, version: int) -> None:
        from app.workers.ingest import chunk_document

        chunk_document.send(document_id, version)

    def enqueue_index_repair(self, org_id: str, kb_id: str) -> None:
        from app.workers.indexing import repair_kb_index

        repair_kb_index.send(org_id, kb_id)

    def enqueue_eval_run(self, run_id: str) -> None:
        from app.workers.evaluation import run_evaluation

        run_evaluation.send(run_id)

    def enqueue_directory_sync(self, run_id: str) -> None:
        from app.workers.directory import sync_directory

        sync_directory.send(run_id)


@dataclass
class RecordingTaskQueue:
    """Collects enqueued tasks (tests drive the pipeline explicitly)."""

    calls: list[tuple[str, str, int]] = field(default_factory=list)
    repairs: list[tuple[str, str]] = field(default_factory=list)
    eval_runs: list[str] = field(default_factory=list)
    directory_runs: list[str] = field(default_factory=list)

    def enqueue_parse(self, document_id: str, version: int) -> None:
        self.calls.append(("parse", document_id, version))

    def enqueue_chunk(self, document_id: str, version: int) -> None:
        self.calls.append(("chunk", document_id, version))

    def enqueue_index_repair(self, org_id: str, kb_id: str) -> None:
        self.repairs.append((org_id, kb_id))

    def enqueue_eval_run(self, run_id: str) -> None:
        self.eval_runs.append(run_id)

    def enqueue_directory_sync(self, run_id: str) -> None:
        self.directory_runs.append(run_id)
