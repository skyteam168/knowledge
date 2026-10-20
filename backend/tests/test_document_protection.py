"""Document protection: watermarked page previews, download permission, copy-protect flags."""

import io
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.core.storage import MemoryStorage
from app.models import Document, KnowledgeBase, User
from app.services.ingest.chunker import Chunker
from app.services.ingest.parsers import ParserRegistry
from app.services.ingest.pipeline import IngestPipeline
from app.services.ingest.queue import RecordingTaskQueue
from app.services.knowledge.page_links import signed_asset_url, verify_asset_link, watermark_lines
from app.services.knowledge.protection import protection_of
from app.services.knowledge.watermark import watermark_png
from tests.conftest import auth
from tests.samples import make_pdf
from tests.test_indexing import BOB, create_kb, me

ALICE, CAROL = auth("alice-token"), auth("carol-token")
DOCS = "/api/v1/documents"


@pytest.fixture
def pipeline(
    settings: Settings, engine: AsyncEngine, storage: MemoryStorage, task_queue: RecordingTaskQueue
) -> IngestPipeline:
    return IngestPipeline(
        session_factory=create_session_factory(engine),
        storage=storage,
        parsers=ParserRegistry(settings.model_copy(update={"pdf_parser": "basic"})),
        chunker=Chunker(),
        queue=task_queue,
        settings=settings,
    )


def test_document_settings_can_only_tighten_the_knowledge_base() -> None:
    kb = KnowledgeBase(watermark=True, copy_protect=False, download_permission="edit")
    loose = Document(watermark=False, copy_protect=None, download_permission="read")
    p = protection_of(kb, loose)
    assert (p.watermark, p.copy_protect, p.download_permission) == (True, False, "edit")
    strict = Document(watermark=None, copy_protect=True, download_permission="manage")
    p = protection_of(kb, strict)
    assert (p.watermark, p.copy_protect, p.download_permission) == (True, True, "manage")
    assert not p.can_download("edit") and p.can_download("manage") and not p.can_download(None)
    plain = protection_of(
        KnowledgeBase(watermark=False, copy_protect=False, download_permission="read")
    )
    assert plain.raw_preview("read") and not p.raw_preview("manage")


def test_watermark_is_burned_into_the_page() -> None:
    page = Image.new("RGB", (400, 300), "white")
    buf = io.BytesIO()
    page.save(buf, format="PNG")
    out = Image.open(io.BytesIO(watermark_png(buf.getvalue(), ["张三", "zhangsan · 1001"])))
    assert out.size == (400, 300)
    darkest, _ = out.convert("L").getextrema()
    assert isinstance(darkest, int) and darkest < 255  # something was drawn on the white page


def test_signed_links_bind_asset_viewer_and_expiry() -> None:
    settings = Settings(presign_expiry_seconds=60, public_base_url="https://kb.example")
    url = signed_asset_url(settings, "a1", "u1", absolute=True)
    parts = urlsplit(url)
    assert url.startswith("https://kb.example/api/v1/assets/pages/a1?")
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert verify_asset_link(settings, "a1", "u1", int(q["e"]), q["s"])
    assert not verify_asset_link(settings, "a2", "u1", int(q["e"]), q["s"])
    assert not verify_asset_link(settings, "a1", "u2", int(q["e"]), q["s"])
    assert not verify_asset_link(settings, "a1", "u1", int(q["e"]) - 3600, q["s"])
    lines = watermark_lines(
        User(username="hien", display_name="Hien", employee_no="26003932"), settings
    )
    assert lines[:2] == ["Hien", "hien · 26003932"]
    assert lines[2].endswith("UTC+8")  # analytics_timezone defaults to Asia/Shanghai


async def _protected_pdf(
    api: httpx.AsyncClient, pipeline: IngestPipeline, name: str, **policy: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    await me(api, CAROL)
    kb = await create_kb(api, name)
    resp = await api.put(f"/api/v1/knowledge-bases/{kb['id']}", json=policy, headers=BOB)
    assert resp.status_code == 200, resp.text
    carol = await me(api, CAROL)
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
    resp = await api.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("工艺.pdf", make_pdf(), "application/pdf")},
        headers=BOB,
    )
    doc = dict(resp.json()["document"])
    assert await pipeline.parse(doc["id"], doc["version"])
    return resp.json()["document"], kb


async def test_readers_get_watermarked_pages_and_cannot_download(
    api: httpx.AsyncClient, pipeline: IngestPipeline, engine: AsyncEngine
) -> None:
    doc, _ = await _protected_pdf(
        api, pipeline, "受控库", watermark=True, copy_protect=True, download_permission="edit"
    )

    detail = (await api.get(f"{DOCS}/{doc['id']}", headers=CAROL)).json()
    assert detail["protection"] == {
        "watermark": True,
        "copy_protect": True,
        "download_permission": "edit",
    }
    assert detail["can_download"] is False

    preview = (await api.get(f"{DOCS}/{doc['id']}/preview-url", headers=CAROL)).json()
    assert preview["mode"] == "pages" and preview["url"] is None and preview["pages"]
    page_url = preview["pages"][0]["url"]
    assert page_url.startswith("/api/v1/assets/pages/")
    image = await api.get(page_url)
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert "private" in image.headers["cache-control"]
    tampered = await api.get(page_url[:-2] + ("AA" if not page_url.endswith("AA") else "BB"))
    assert tampered.status_code == 403

    denied = await api.get(f"{DOCS}/{doc['id']}/download-url", headers=CAROL)
    assert denied.status_code == 403 and denied.json()["code"] == "DOWNLOAD_FORBIDDEN"
    allowed = await api.get(f"{DOCS}/{doc['id']}/download-url", headers=BOB)
    assert allowed.status_code == 200 and allowed.json()["url"]


async def test_documents_can_tighten_protection_with_manage_permission(
    api: httpx.AsyncClient, pipeline: IngestPipeline
) -> None:
    doc, _ = await _protected_pdf(api, pipeline, "普通库")
    # No protection: the original file is shown inline and readers may download it.
    preview = (await api.get(f"{DOCS}/{doc['id']}/preview-url", headers=CAROL)).json()
    assert preview["mode"] == "file" and preview["url"]
    assert (await api.get(f"{DOCS}/{doc['id']}/download-url", headers=CAROL)).status_code == 200

    forbidden = await api.put(f"{DOCS}/{doc['id']}", json={"watermark": True}, headers=CAROL)
    assert forbidden.status_code == 403
    resp = await api.put(
        f"{DOCS}/{doc['id']}",
        json={"watermark": True, "download_permission": "manage"},
        headers=BOB,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["protection"]["download_permission"] == "manage"
    preview = (await api.get(f"{DOCS}/{doc['id']}/preview-url", headers=CAROL)).json()
    assert preview["mode"] == "pages"
    assert (await api.get(f"{DOCS}/{doc['id']}/download-url", headers=CAROL)).status_code == 403

    reset = await api.put(
        f"{DOCS}/{doc['id']}", json={"watermark": None, "download_permission": None}, headers=BOB
    )
    assert reset.json()["protection"]["watermark"] is False
