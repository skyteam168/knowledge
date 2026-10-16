"""Hardening: rate limits, upload screening (sniffing + virus scan) and PII masking."""

import asyncio
import struct

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.cache import MemoryCache
from app.core.config import Settings
from app.core.rate_limit import RateLimitedError, RateLimiter, buckets
from app.services.indexing.runtime import IndexingRuntime
from app.services.ingest.parsers.base import FileKind
from app.services.ingest.pipeline import IngestPipeline
from app.services.security.file_guard import (
    ClamAvScanner,
    FileContentMismatchError,
    FileGuard,
    InfectedFileError,
    ScanResult,
    ScanUnavailableError,
    content_matches,
)
from app.services.security.pii import PiiMasker, StreamMasker
from tests.conftest import auth
from tests.samples import LOREM_ZH
from tests.test_chat_api import ask, new_conversation
from tests.test_indexing import child_chunks, create_kb, drain, ingest, me, pipeline

__all__ = ["pipeline"]

ALICE, BOB = auth("alice-token"), auth("bob-token")

# Checksum-valid samples.
ID_CARD = "11010519491231002X"
BANK_CARD = "6222020200112233446"  # Luhn-valid 19 digits


# ---- rate limiting -------------------------------------------------------------------------


def test_bucket_classification() -> None:
    assert buckets("POST", "/api/v1/chat/conversations/c1/messages") == ("api", "chat")
    assert buckets("GET", "/api/v1/chat/conversations/c1/messages") == ("api",)
    assert buckets("POST", "/api/v1/knowledge-bases/k1/documents") == ("api", "upload")
    assert buckets("POST", "/api/v1/knowledge-bases/k1/documents/upload-url") == ("api", "upload")
    assert buckets("GET", "/api/v1/search") == ("api",)


async def test_rate_limiter_per_user_and_per_org(settings: Settings) -> None:
    cfg = settings.model_copy(update={"rate_limit_user_requests": 2, "rate_limit_org_requests": 3})
    limiter = RateLimiter(MemoryCache(), cfg)
    for _ in range(2):
        await limiter.check(user_id="u1", org_id="o1", method="GET", path="/x")
    with pytest.raises(RateLimitedError) as exc:
        await limiter.check(user_id="u1", org_id="o1", method="GET", path="/x")
    assert exc.value.detail["scope"] == "user"
    assert exc.value.headers and int(exc.value.headers["Retry-After"]) >= 1
    # Another user of the same org: org budget (3) is exhausted after one more call.
    await limiter.check(user_id="u2", org_id="o1", method="GET", path="/x")
    with pytest.raises(RateLimitedError) as exc:
        await limiter.check(user_id="u3", org_id="o1", method="GET", path="/x")
    assert exc.value.detail["scope"] == "org"
    await limiter.check(user_id="u9", org_id="o2", method="GET", path="/x")


async def test_rate_limiter_fails_open(settings: Settings) -> None:
    class Broken(MemoryCache):
        async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
            raise ConnectionError("redis down")

    limiter = RateLimiter(Broken(), settings.model_copy(update={"rate_limit_user_requests": 1}))
    for _ in range(3):
        await limiter.check(user_id="u", org_id="o", method="GET", path="/x")


async def test_api_returns_429_with_retry_after(
    api: httpx.AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_user_requests", 2)
    assert (await api.get("/api/v1/auth/me", headers=BOB)).status_code == 200
    assert (await api.get("/api/v1/auth/me", headers=BOB)).status_code == 200
    resp = await api.get("/api/v1/auth/me", headers=BOB)
    assert resp.status_code == 429
    body = resp.json()
    assert body["code"] == "RATE_LIMITED" and body["trace_id"]
    assert int(resp.headers["Retry-After"]) >= 1
    # Other users are unaffected.
    assert (await api.get("/api/v1/auth/me", headers=ALICE)).status_code == 200


# ---- upload screening ----------------------------------------------------------------------


def test_content_sniffing() -> None:
    assert content_matches(FileKind.PDF, b"%PDF-1.7\n...")
    assert not content_matches(FileKind.PDF, b"MZ\x90\x00")
    assert content_matches(FileKind.WORD, b"PK\x03\x04rest")
    assert content_matches(FileKind.WORD, b"\xd0\xcf\x11\xe0legacy-doc")
    assert not content_matches(FileKind.EXCEL, b"\xd0\xcf\x11\xe0legacy")
    assert content_matches(FileKind.IMAGE, b"\xff\xd8\xff\xe0rest")
    assert content_matches(FileKind.IMAGE, b"\x89PNG\r\n\x1a\nrest")
    assert not content_matches(FileKind.IMAGE, b"PK\x03\x04")
    assert content_matches(FileKind.MARKDOWN, "# 标题\n正文".encode())
    assert not content_matches(FileKind.TEXT, b"MZ\x90\x00\x03")
    assert not content_matches(FileKind.CSV, b"a,b\x00\x00c")


class FakeScanner:
    name = "fake"

    def __init__(self, infected: bool) -> None:
        self.infected = infected
        self.scanned: list[int] = []

    async def scan(self, data: bytes) -> ScanResult:
        self.scanned.append(len(data))
        if self.infected:
            return ScanResult(clean=False, signature="Eicar-Test-Signature", engine=self.name)
        return ScanResult(clean=True, engine=self.name)


async def test_file_guard(settings: Settings) -> None:
    clean = FileGuard(settings, FakeScanner(infected=False))
    await clean.check(FileKind.MARKDOWN, "a.md", b"# ok")
    with pytest.raises(FileContentMismatchError):
        await clean.check(FileKind.PDF, "fake.pdf", b"#!/bin/sh\nrm -rf /")
    with pytest.raises(InfectedFileError):
        await FileGuard(settings, FakeScanner(infected=True)).check(FileKind.TEXT, "a.txt", b"x")


async def test_upload_rejects_disguised_and_disallowed_files(
    api: httpx.AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    await me(api, BOB)
    kb = await create_kb(api, "上传校验")
    url = f"/api/v1/knowledge-bases/{kb['id']}/documents"
    exe = await api.post(
        url, files={"file": ("report.pdf", b"MZ\x90\x00binary", "application/pdf")}, headers=BOB
    )
    assert exe.status_code == 415 and exe.json()["code"] == "FILE_CONTENT_MISMATCH"

    monkeypatch.setattr(settings, "upload_allowed_kinds", ["pdf"])
    md = await api.post(url, files={"file": ("a.md", b"# hi", "text/markdown")}, headers=BOB)
    assert md.status_code == 415 and md.json()["code"] == "UNSUPPORTED_FILE_TYPE"
    assert md.json()["detail"]["allowed"] == ["pdf"]

    monkeypatch.setattr(settings, "upload_allowed_kinds", [])
    monkeypatch.setattr(settings, "upload_max_bytes", 3)
    big = await api.post(url, files={"file": ("a.md", b"# hello", "text/markdown")}, headers=BOB)
    assert big.status_code == 413


async def test_clamav_instream_protocol() -> None:
    received = bytearray()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        while True:
            (size,) = struct.unpack(">I", await reader.readexactly(4))
            if size == 0:
                break
            received.extend(await reader.readexactly(size))
        found = b"EICAR" in received
        writer.write(b"stream: Eicar-Test-Signature FOUND\0" if found else b"stream: OK\0")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        scanner = ClamAvScanner("127.0.0.1", port, timeout=5)
        assert (await scanner.scan(b"hello" * 30000)).clean
        received.clear()
        result = await scanner.scan(b"X5O!P%@AP EICAR test")
        assert not result.clean and result.signature == "Eicar-Test-Signature"
    with pytest.raises(ScanUnavailableError):
        await ClamAvScanner("127.0.0.1", port, timeout=1).scan(b"x")


# ---- PII ------------------------------------------------------------------------------------


def test_pii_detection_and_masking() -> None:
    masker = PiiMasker(["phone", "id_card", "bank_card", "email"])
    text = (
        f"张三，手机 13812345678，身份证 {ID_CARD}，卡号 {BANK_CARD}，"
        "邮箱 zhangsan@example.com，订单号 20240101123456789 不是卡号。"
    )
    found = {m.type: m.value for m in masker.find(text)}
    assert found == {
        "phone": "13812345678",
        "id_card": ID_CARD,
        "bank_card": BANK_CARD,
        "email": "zhangsan@example.com",
    }
    masked = masker.mask(text)
    assert "138****5678" in masked
    assert "110***********002X" in masked
    assert "6222***********3446" in masked
    assert "z***@example.com" in masked
    assert "20240101123456789" in masked
    # An 18-digit number with a wrong checksum is not an ID card.
    assert PiiMasker(["id_card"]).find("110105194912310021") == []
    assert PiiMasker([]).mask(text) == text
    with pytest.raises(ValueError):
        PiiMasker(["passport"])


async def test_output_masking_in_answers_and_search(
    api: httpx.AsyncClient,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_evidence_min_score", 0.0)
    monkeypatch.setattr(settings, "chat_evidence_confident_score", 0.0)
    monkeypatch.setattr(settings, "pii_mask_on_output", True)
    await me(api, BOB)
    kb = await create_kb(api, "通讯录", visibility="org")
    body = (
        "# 值班联系人\n\n## 联系方式\n\n值班电话 13812345678，请在工作时间拨打。\n\n"
        f"## 背景\n\n{LOREM_ZH}\n"
    )
    await ingest(api, pipeline, kb["id"], "contacts.md", body.encode())
    await drain(indexing)

    search = await api.get("/api/v1/search", params={"q": "值班电话"}, headers=BOB)
    assert search.status_code == 200
    raw = search.text
    assert "13812345678" not in raw and "138****5678" in raw

    conv = await new_conversation(api, BOB)
    result = await ask(api, BOB, conv["id"], "值班电话是多少？")
    assert "13812345678" not in result["text"]
    assert "13812345678" not in result["done"]["answer"]
    assert all("13812345678" not in c["quote"] for c in result["citations"]["citations"])


async def test_ingest_masking_keeps_pii_out_of_chunks(
    api: httpx.AsyncClient, pipeline: IngestPipeline, engine: AsyncEngine
) -> None:
    pipeline.masker = PiiMasker(["phone", "id_card"])
    await me(api, BOB)
    kb = await create_kb(api, "人员档案")
    body = f"# 档案\n\n## 信息\n\n身份证 {ID_CARD}，电话 13812345678。\n\n## 背景\n\n{LOREM_ZH}\n"
    doc = await ingest(api, pipeline, kb["id"], "people.md", body.encode())
    text = "\n".join(c.content for c in await child_chunks(engine, doc["id"]))
    assert ID_CARD not in text and "13812345678" not in text
    assert "138****5678" in text


def test_stream_masker_handles_numbers_split_across_tokens() -> None:
    masker = PiiMasker(["phone", "id_card"])
    text = f"请联系 13812345678 或核对身份证号 {ID_CARD} 之后再处理后续流程。" * 3
    stream = StreamMasker(masker, hold=24)
    out = ""
    for i in range(0, len(text), 3):
        out += stream.feed(text[i : i + 3])
    out += stream.flush()
    assert out == masker.mask(text)
    assert "13812345678" not in out and ID_CARD not in out
