"""Attach / resolve presigned page/slide images for answers, citations, and Open API."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.storage import ObjectStorage
from app.models import PageAssetKind
from app.repositories.knowledge_repo import DocumentPageAssetRepository
from app.services.chat.evidence import Evidence, MaterialImage

IMAGE_REF_PREFIX = "ekb-image:"


async def resolve_page_image(
    session: AsyncSession,
    storage: ObjectStorage | None,
    settings: Settings,
    *,
    document_id: str,
    version: int,
    slide_number: int | None,
    page_start: int | None,
) -> tuple[str | None, str | None]:
    """Return (presigned_url, mime_type) for the page/slide used by a citation or hit."""
    if storage is None or not settings.page_image_enabled:
        return None, None
    asset = await DocumentPageAssetRepository(session).find_for_citation(
        document_id,
        version,
        slide_number=slide_number,
        page_start=page_start,
    )
    if asset is None:
        return None, None
    url = storage.presign_get(
        asset.minio_key,
        settings.presign_expiry_seconds,
        filename=f"{asset.kind}-{asset.page_index}.png",
        content_type=asset.mime_type,
        attachment=False,
    )
    return url, asset.mime_type


async def attach_material_images(
    session: AsyncSession,
    evidences: Sequence[Evidence],
    storage: ObjectStorage | None,
    settings: Settings,
) -> None:
    """Mutate evidences in place: fill `images` with capped, ACL-already-checked assets."""
    if (
        storage is None
        or not settings.page_image_enabled
        or not settings.chat_answer_images_enabled
    ):
        return
    per_material = max(0, settings.chat_answer_images_per_material)
    total_budget = max(0, settings.chat_answer_images_total)
    if per_material == 0 or total_budget == 0:
        return

    repo = DocumentPageAssetRepository(session)
    remaining = total_budget
    expires = settings.presign_expiry_seconds
    seq = 0

    for ev in evidences:
        if remaining <= 0 or ev.is_ko:
            continue
        kind, indices = _wanted_indices(ev, per_material)
        if not indices:
            continue
        indices = indices[:remaining]
        assets = await repo.list_by_indices(
            ev.document.id, ev.document.version, kind, indices
        )
        by_index = {a.page_index: a for a in assets}
        images: list[MaterialImage] = []
        for index in indices:
            asset = by_index.get(index)
            if asset is None:
                continue
            caption = _caption(kind, index)
            url = storage.presign_get(
                asset.minio_key,
                expires,
                filename=f"{asset.kind}-{asset.page_index}.png",
                content_type=asset.mime_type,
                attachment=False,
            )
            seq += 1
            images.append(
                MaterialImage(
                    url=url,
                    caption=caption,
                    mime_type=asset.mime_type,
                    ref=f"{IMAGE_REF_PREFIX}{seq}",
                )
            )
            remaining -= 1
            if remaining <= 0:
                break
        ev.images = images


def _wanted_indices(ev: Evidence, limit: int) -> tuple[str, list[int]]:
    if limit <= 0:
        return PageAssetKind.PAGE.value, []
    if ev.slide_number is not None:
        return PageAssetKind.SLIDE.value, [ev.slide_number]
    if ev.page_start is None:
        return PageAssetKind.PAGE.value, []
    end = ev.page_end if ev.page_end is not None else ev.page_start
    if end < ev.page_start:
        end = ev.page_start
    return PageAssetKind.PAGE.value, list(range(ev.page_start, end + 1))[:limit]


def _caption(kind: str, index: int) -> str:
    if kind == PageAssetKind.SLIDE.value:
        return f"第 {index} 张幻灯片"
    return f"第 {index} 页"


def answer_image_targets(evidences: Sequence[Evidence]) -> dict[str, str]:
    """Image address the model may write (placeholder ref or exact URL) -> real URL."""
    targets: dict[str, str] = {}
    for ev in evidences:
        for img in ev.images:
            targets[img.url] = img.url
            if img.ref:
                targets[img.ref] = img.url
    return targets
