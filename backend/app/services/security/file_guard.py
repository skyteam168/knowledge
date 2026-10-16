"""Upload screening: content sniffing (the bytes must match the extension) and virus scanning.

`VirusScanner` is the extension point: `NoopScanner` (default) or `ClamAvScanner` (clamd
INSTREAM over TCP). Other engines implement the same protocol.
"""

import asyncio
import logging
import struct
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import AppError
from app.services.ingest.parsers.base import FileKind

logger = logging.getLogger(__name__)

_OOXML = b"PK\x03\x04"
_OLE2 = b"\xd0\xcf\x11\xe0"  # legacy .doc / .xls / .ppt
_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"
_BINARY_MAGIC = (
    b"%PDF-",
    _OOXML,
    b"MZ",  # Windows executables
    b"\x7fELF",
    _OLE2,
    b"\xca\xfe\xba\xbe",  # Mach-O / Java class
    b"\x1f\x8b",  # gzip
    b"Rar!",
    b"7z\xbc\xaf",
    _JPEG,
    _PNG,
)
_TEXT_KINDS = {FileKind.TEXT, FileKind.MARKDOWN, FileKind.CSV, FileKind.HTML}
SNIFF_BYTES = 4096


class FileContentMismatchError(AppError):
    status_code = 415
    code = "FILE_CONTENT_MISMATCH"
    message = "File content does not match its type"


class InfectedFileError(AppError):
    status_code = 422
    code = "FILE_INFECTED"
    message = "The file was rejected by the virus scanner"


class ScanUnavailableError(AppError):
    status_code = 503
    code = "VIRUS_SCAN_UNAVAILABLE"
    message = "Virus scanning is temporarily unavailable"


def content_matches(kind: FileKind, head: bytes) -> bool:
    if kind == FileKind.PDF:
        # Some generators prepend a few bytes before the header.
        return b"%PDF-" in head[:1024]
    if kind == FileKind.WORD:
        # .docx is OOXML (ZIP); legacy .doc is OLE2.
        return head.startswith(_OOXML) or head.startswith(_OLE2)
    if kind in (FileKind.EXCEL, FileKind.PPT):
        return head.startswith(_OOXML)
    if kind == FileKind.IMAGE:
        return head.startswith(_JPEG) or head.startswith(_PNG)
    if kind in _TEXT_KINDS:
        if any(head.startswith(m) for m in _BINARY_MAGIC):
            return False
        sample = head[:SNIFF_BYTES]
        if sample.startswith((b"\xff\xfe", b"\xfe\xff")):  # UTF-16 text
            return True
        return b"\x00" not in sample
    return False


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None = None
    engine: str = "none"


class VirusScanner(Protocol):
    name: str

    async def scan(self, data: bytes) -> ScanResult: ...


class NoopScanner:
    name = "none"

    async def scan(self, data: bytes) -> ScanResult:
        return ScanResult(clean=True)


class ClamAvScanner:
    """clamd INSTREAM protocol: `zINSTREAM\\0`, <len:uint32 BE><chunk>..., <0:uint32>."""

    name = "clamav"
    CHUNK = 64 * 1024

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    async def _scan(self, data: bytes) -> ScanResult:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        try:
            writer.write(b"zINSTREAM\0")
            for i in range(0, len(data), self.CHUNK):
                chunk = data[i : i + self.CHUNK]
                writer.write(struct.pack(">I", len(chunk)) + chunk)
                await writer.drain()
            writer.write(struct.pack(">I", 0))
            await writer.drain()
            reply = (await reader.read(4096)).rstrip(b"\0").decode("utf-8", "replace").strip()
        finally:
            writer.close()
            await writer.wait_closed()
        # "stream: OK" | "stream: <signature> FOUND" | "INSTREAM size limit exceeded. ERROR"
        if reply.endswith("OK"):
            return ScanResult(clean=True, engine=self.name)
        if reply.endswith("FOUND"):
            signature = reply.removeprefix("stream:").removesuffix("FOUND").strip()
            return ScanResult(clean=False, signature=signature, engine=self.name)
        raise ScanUnavailableError(detail={"reply": reply[:200]})

    async def scan(self, data: bytes) -> ScanResult:
        try:
            return await asyncio.wait_for(self._scan(data), self.timeout)
        except (OSError, TimeoutError) as exc:
            logger.warning("virus_scan_unavailable", extra={"error": str(exc)})
            raise ScanUnavailableError() from exc


def build_scanner(settings: Settings) -> VirusScanner:
    if settings.virus_scan_backend == "clamav":
        return ClamAvScanner(
            settings.clamav_host, settings.clamav_port, settings.clamav_timeout_seconds
        )
    return NoopScanner()


class FileGuard:
    def __init__(self, settings: Settings, scanner: VirusScanner | None = None) -> None:
        self.settings = settings
        self.scanner = scanner or build_scanner(settings)

    @property
    def inspects_content(self) -> bool:
        return self.settings.upload_sniff_content or self.scanner.name != "none"

    async def check(self, kind: FileKind, filename: str, data: bytes) -> ScanResult:
        if self.settings.upload_sniff_content and not content_matches(kind, data[:SNIFF_BYTES]):
            raise FileContentMismatchError(detail={"filename": filename, "kind": kind.value})
        result = await self.scanner.scan(data)
        if not result.clean:
            logger.warning(
                "upload_infected",
                extra={"upload_filename": filename, "signature": result.signature},
            )
            raise InfectedFileError(detail={"filename": filename, "signature": result.signature})
        return result
