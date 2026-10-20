"""Document versions: view, compare and restore older uploads."""

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.core.storage import MemoryStorage
from app.services.ingest.chunker import Chunker
from app.services.ingest.parsers import ParserRegistry
from app.services.ingest.pipeline import IngestPipeline
from app.services.ingest.queue import RecordingTaskQueue
from app.services.ingest.sections import SectionBuilder
from app.services.knowledge.version_diff import diff_lines, document_lines
from tests.conftest import auth
from tests.test_indexing import BOB, create_kb, me

CAROL = auth("carol-token")
DOCS = "/api/v1/documents"
V1 = "# 工艺规范\n\n温度 180 度。\n\n压力 2 MPa。\n\n## 检验\n\n每批抽检 5 件。\n"
V2 = "# 工艺规范\n\n温度 200 度。\n\n压力 2 MPa。\n\n## 检验\n\n每批抽检 5 件。\n\n记录存档。\n"


@pytest.fixture
def pipeline(
    settings: Settings, engine: AsyncEngine, storage: MemoryStorage, task_queue: RecordingTaskQueue
) -> IngestPipeline:
    return IngestPipeline(
        session_factory=create_session_factory(engine),
        storage=storage,
        parsers=ParserRegistry(settings),
        chunker=Chunker(),
        queue=task_queue,
        settings=settings,
    )


def test_diff_marks_changed_lines_with_context() -> None:
    old = [f"line {i}" for i in range(20)]
    new = [*old[:10], "changed", *old[11:], "tail"]
    diff = diff_lines(old, new, context=2)
    assert (diff.added, diff.removed, diff.truncated) == (2, 1, False)
    first = diff.hunks[0]
    assert [line.op for line in first] == ["equal", "equal", "del", "add", "equal", "equal"]
    assert first[2].text == "line 10" and first[2].old_no == 11 and first[2].new_no is None
    assert first[3].text == "changed" and first[3].new_no == 11
    assert diff_lines(old, old).hunks == []
    capped = diff_lines(old, [f"x {i}" for i in range(20)], limit=10)
    assert capped.truncated and capped.hunks == []


def test_document_lines_keep_headings_and_mask() -> None:
    builder = SectionBuilder()
    builder.heading("规范", 1)
    builder.text("联系 13800138000\n\n  ")
    parsed = builder.build("test")
    lines, truncated = document_lines(parsed, lambda s: s.replace("13800138000", "***"))
    assert lines == ["# 规范", "联系 ***"] and not truncated


async def _upload(api: httpx.AsyncClient, kb_id: str, text: str) -> dict[str, Any]:
    resp = await api.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        files={"file": ("规范.md", text.encode(), "text/markdown")},
        headers=BOB,
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json()["document"])


async def _two_versions(
    api: httpx.AsyncClient, pipeline: IngestPipeline
) -> tuple[dict[str, Any], dict[str, Any]]:
    carol = await me(api, CAROL)
    kb = await create_kb(api, "版本库")
    acl = {
        "visibility": "restricted",
        "entries": [
            {
                "principal_type": "user",
                "principal_id": (await me(api, BOB))["id"],
                "permission": "manage",
            },
            {"principal_type": "user", "principal_id": carol["id"], "permission": "read"},
        ],
    }
    assert (
        await api.put(f"/api/v1/knowledge-bases/{kb['id']}/acl", json=acl, headers=BOB)
    ).status_code == 200
    first = await _upload(api, kb["id"], V1)
    assert await pipeline.parse(first["id"], 1)
    second = await _upload(api, kb["id"], V2)
    assert second["id"] == first["id"] and second["version"] == 2
    assert await pipeline.parse(second["id"], 2)
    return second, kb


async def test_readers_can_view_and_compare_versions(
    api: httpx.AsyncClient, pipeline: IngestPipeline
) -> None:
    doc, _ = await _two_versions(api, pipeline)
    detail = (await api.get(f"{DOCS}/{doc['id']}", headers=CAROL)).json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    assert detail["versions"][0]["created_by_name"]

    text = (await api.get(f"{DOCS}/{doc['id']}/versions/1/text", headers=CAROL)).json()
    assert text["available"] and "温度 180 度。" in text["lines"]
    preview = (await api.get(f"{DOCS}/{doc['id']}/versions/1/preview-url", headers=CAROL)).json()
    assert preview["mode"] == "file" and preview["url"]
    old_file = await api.get(f"{DOCS}/{doc['id']}/versions/1/download-url", headers=CAROL)
    assert old_file.status_code == 200 and "/v1/" in old_file.json()["url"]
    missing = await api.get(f"{DOCS}/{doc['id']}/versions/9/text", headers=CAROL)
    assert missing.status_code == 404

    resp = await api.get(
        f"{DOCS}/{doc['id']}/versions/compare", params={"base": 1, "target": 2}, headers=CAROL
    )
    assert resp.status_code == 200, resp.text
    diff = resp.json()
    assert diff["available"] and not diff["same_file"]
    assert (diff["added"], diff["removed"]) == (2, 1)
    changed = {(line["op"], line["text"]) for hunk in diff["hunks"] for line in hunk}
    assert {("del", "温度 180 度。"), ("add", "温度 200 度。"), ("add", "记录存档。")} <= changed


async def test_restoring_a_version_creates_a_new_one(
    api: httpx.AsyncClient, pipeline: IngestPipeline, task_queue: RecordingTaskQueue
) -> None:
    doc, _ = await _two_versions(api, pipeline)
    url = f"{DOCS}/{doc['id']}/versions/1/restore"
    assert (await api.post(url, headers=CAROL)).status_code == 403
    current = await api.post(f"{DOCS}/{doc['id']}/versions/2/restore", headers=BOB)
    assert current.status_code == 409

    resp = await api.post(url, headers=BOB)
    assert resp.status_code == 200, resp.text
    restored = resp.json()
    assert restored["version"] == 3 and restored["status"] == "uploaded"
    assert ("parse", doc["id"], 3) in task_queue.calls

    detail = (await api.get(f"{DOCS}/{doc['id']}", headers=BOB)).json()
    newest, _, oldest = detail["versions"]
    assert newest["version"] == 3 and newest["restored_from"] == 1
    assert newest["sha256"] == oldest["sha256"] == detail["sha256"]
    assert await pipeline.parse(doc["id"], 3)
    same = await api.get(
        f"{DOCS}/{doc['id']}/versions/compare", params={"base": 1, "target": 3}, headers=BOB
    )
    assert same.json()["same_file"] and same.json()["hunks"] == []
