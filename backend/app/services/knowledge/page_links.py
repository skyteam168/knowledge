"""Links to page / slide images.

Unprotected documents keep presigned object-storage URLs. Documents with a watermark get a
short-lived signed link to `/api/v1/assets/pages/{asset_id}`, which renders the page with the
viewer's name burned in; the signature binds asset, viewer and expiry, so a forwarded link still
shows who it was issued to and stops working after it expires.
"""

import asyncio
import base64
import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.storage import ObjectStorage
from app.models import Document, DocumentPageAsset, KnowledgeBase, User
from app.services.knowledge.protection import Protection, protection_of
from app.services.knowledge.watermark import watermark_png

ASSET_PATH = "/api/v1/assets/pages/"


def _key(settings: Settings) -> bytes:
    return hmac.new(
        settings.directory_secret_key.encode(), b"ekb-page-asset-v1", hashlib.sha256
    ).digest()


def _signature(settings: Settings, asset_id: str, viewer_id: str, expires: int) -> str:
    mac = hmac.new(_key(settings), f"{asset_id}.{viewer_id}.{expires}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()[:24]).decode().rstrip("=")


def signed_asset_url(
    settings: Settings, asset_id: str, viewer_id: str, *, absolute: bool = False
) -> str:
    expires = int(time.time()) + settings.presign_expiry_seconds
    query = urlencode(
        {"u": viewer_id, "e": expires, "s": _signature(settings, asset_id, viewer_id, expires)}
    )
    base = settings.public_base_url.rstrip("/") if absolute else ""
    return f"{base}{ASSET_PATH}{asset_id}?{query}"


def verify_asset_link(
    settings: Settings, asset_id: str, viewer_id: str, expires: int, signature: str
) -> bool:
    if expires < int(time.time()):
        return False
    expected = _signature(settings, asset_id, viewer_id, expires)
    return hmac.compare_digest(expected, signature)


def watermark_lines(viewer: User, settings: Settings, now: datetime | None = None) -> list[str]:
    """Who and when: name, account · employee no., local date and time."""
    detail = " · ".join(p for p in (viewer.username, viewer.employee_no) if p)
    moment = (now or datetime.now(UTC)).astimezone(ZoneInfo(settings.analytics_timezone))
    offset = int((moment.utcoffset() or timedelta()).total_seconds() // 3600)
    stamp = f"{moment:%Y-%m-%d %H:%M} UTC{offset:+d}"
    return [viewer.display_name or viewer.username, detail, stamp]


async def render_watermarked_page(
    session: AsyncSession,
    storage: ObjectStorage,
    settings: Settings,
    *,
    asset_id: str,
    viewer_id: str,
    expires: int,
    signature: str,
) -> bytes:
    """The page image of a valid signed link, with the viewer's watermark burned in."""
    if not verify_asset_link(settings, asset_id, viewer_id, expires, signature):
        raise PermissionDeniedError("Link expired or invalid", code="ASSET_LINK_INVALID")
    asset = await session.get(DocumentPageAsset, asset_id)
    viewer = await session.get(User, viewer_id)
    if asset is None or viewer is None or viewer.org_id != asset.org_id or not viewer.is_active:
        raise NotFoundError("Page not found")
    data = await storage.get_bytes(asset.minio_key)
    return await asyncio.to_thread(watermark_png, data, watermark_lines(viewer, settings))


class PageLinks:
    """Builds page image URLs for one viewer, loading each document's protection once."""

    def __init__(
        self,
        session: AsyncSession,
        storage: ObjectStorage,
        settings: Settings,
        viewer_id: str,
        *,
        absolute: bool = False,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.viewer_id = viewer_id
        self.absolute = absolute
        self._protection: dict[str, Protection] = {}

    async def protection(self, document_id: str) -> Protection:
        if document_id not in self._protection:
            doc = await self.session.get(Document, document_id)
            kb = await self.session.get(KnowledgeBase, doc.kb_id) if doc else None
            self._protection[document_id] = (
                protection_of(kb, doc) if doc and kb else Protection(watermark=True)
            )
        return self._protection[document_id]

    async def url(self, asset: DocumentPageAsset) -> str:
        if (await self.protection(asset.document_id)).watermark:
            return signed_asset_url(self.settings, asset.id, self.viewer_id, absolute=self.absolute)
        return self.storage.presign_get(
            asset.minio_key,
            self.settings.presign_expiry_seconds,
            filename=f"{asset.kind}-{asset.page_index}.png",
            content_type=asset.mime_type,
            attachment=False,
        )
