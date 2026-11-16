"""Build lightweight related-concept cards for the chat UI (no graph layout)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EquipDevice, EquipSparePart, EquipWorkOrder, StructuredObjectType
from app.repositories.structured_repo import StructuredRepository
from app.repositories.terminology_repo import TerminologyRepository
from app.services.knowledge.ko_access import KoAccess
from app.services.authz import CurrentUser


async def related_concepts_from_matches(
    session: AsyncSession,
    *,
    org_id: str,
    user: CurrentUser,
    matches: list[dict[str, object]],
    allowed_kb_ids: frozenset[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Dedupe terminology matches and attach mirror ids + readable KO titles."""
    if not matches:
        return []
    terms = TerminologyRepository(session)
    structured = StructuredRepository(session)
    kos = KoAccess(session)

    order: list[str] = []
    for match in matches:
        eid = str(match.get("entity_id") or "")
        if eid and eid not in order:
            order.append(eid)
        if len(order) >= limit:
            break

    out: list[dict[str, Any]] = []
    for entity_id in order:
        entity = await terms.get_entity(org_id, entity_id)
        if entity is None:
            continue
        aliases = await terms.list_aliases_for(org_id, [entity_id])
        links = await structured.list_links_for_term(org_id, entity_id)
        mirrors: list[dict[str, str]] = []
        ko_ids: list[str] = []
        for link in links:
            if link.ko_id:
                ko_ids.append(link.ko_id)
            mirror = await _mirror_brief(session, org_id, link.object_type, link.object_id)
            if mirror and mirror not in mirrors:
                mirrors.append(mirror)

        ko_items: list[dict[str, str]] = []
        if ko_ids:
            check = await kos.live_objects(user, ko_ids)
            seen: set[str] = set()
            for kid in ko_ids:
                if kid in seen:
                    continue
                live = check.objects.get(kid)
                if live is None:
                    continue
                if allowed_kb_ids is not None and live.kb.id not in allowed_kb_ids:
                    continue
                seen.add(kid)
                ko_items.append(
                    {
                        "id": live.ko.id,
                        "title": live.ko.title,
                        "ko_type": live.ko.ko_type,
                        "kb_id": live.kb.id,
                    }
                )
                if len(ko_items) >= 5:
                    break

        out.append(
            {
                "entity_id": entity.id,
                "canonical_name": entity.canonical_name,
                "entity_type": entity.entity_type,
                "aliases": [a.alias for a in aliases][:8],
                "mirrors": mirrors[:5],
                "knowledge_objects": ko_items,
            }
        )
    return out


async def _mirror_brief(
    session: AsyncSession, org_id: str, object_type: str, object_id: str
) -> dict[str, str] | None:
    if object_type == StructuredObjectType.DEVICE.value:
        row = await session.get(EquipDevice, object_id)
        if row is None or row.org_id != org_id:
            return None
        return {
            "object_type": object_type,
            "external_id": row.external_id,
            "label": row.name,
        }
    if object_type == StructuredObjectType.WORK_ORDER.value:
        row = await session.get(EquipWorkOrder, object_id)
        if row is None or row.org_id != org_id:
            return None
        return {
            "object_type": object_type,
            "external_id": row.external_id,
            "label": row.title,
        }
    if object_type == StructuredObjectType.SPARE_PART.value:
        row = await session.get(EquipSparePart, object_id)
        if row is None or row.org_id != org_id:
            return None
        return {
            "object_type": object_type,
            "external_id": row.external_id,
            "label": row.name,
        }
    return {
        "object_type": object_type,
        "external_id": object_id,
        "label": object_id,
    }
