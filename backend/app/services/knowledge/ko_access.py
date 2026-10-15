"""PG check of knowledge objects found in the indexes (the indexes are only a pre-filter).

A KO is live for a reader when it is published and not deprecated, inside its effective
window, its knowledge base is live, and the reader can read it now (KB ACL or own ACL).
An index entry is live when it belongs to the live KO's published version.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeBase, KnowledgeObject, KoEntry, KoStatus, KoVersion
from app.models.base import utcnow
from app.repositories.curation_repo import KnowledgeObjectRepository
from app.services.authz import CurrentUser
from app.services.knowledge.access import RESOURCE_KO, KnowledgeAccess


@dataclass(frozen=True)
class LiveKo:
    ko: KnowledgeObject
    snapshot: KoVersion
    kb: KnowledgeBase


@dataclass(frozen=True)
class LiveEntry:
    entry: KoEntry
    live: LiveKo


@dataclass
class KoCheck:
    objects: dict[str, LiveKo] = field(default_factory=dict)
    dropped: Counter[str] = field(default_factory=Counter)


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; values are stored in UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=utcnow().tzinfo)


def in_effect(snapshot: KoVersion, now: datetime) -> bool:
    if snapshot.effective_from is not None and _aware(snapshot.effective_from) > now:
        return False
    return snapshot.effective_to is None or _aware(snapshot.effective_to) > now


class KoAccess:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = KnowledgeObjectRepository(session)
        self.access = KnowledgeAccess(session)

    async def live_objects(self, user: CurrentUser, ko_ids: Sequence[str]) -> KoCheck:
        ids = list(dict.fromkeys(ko_ids))
        result = KoCheck()
        rows = await self.repo.objects_with_kbs(user.org_id, ids)
        result.dropped["not_found"] = len(ids) - len(rows)
        candidates: list[tuple[KnowledgeObject, KnowledgeBase]] = []
        for ko, kb in rows:
            if kb.deleted_at is not None:
                result.dropped["deleted"] += 1
            elif ko.published_version is None or ko.status == KoStatus.DEPRECATED.value:
                result.dropped["unpublished"] += 1
            else:
                candidates.append((ko, kb))
        snapshots = await self.repo.snapshots(
            [(ko.id, ko.published_version) for ko, _ in candidates if ko.published_version]
        )
        now = utcnow()
        in_window: list[tuple[KnowledgeObject, KnowledgeBase, KoVersion]] = []
        for ko, kb in candidates:
            snap = snapshots.get((ko.id, ko.published_version or 0))
            if snap is None:
                result.dropped["not_found"] += 1
            elif not in_effect(snap, now):
                result.dropped["not_in_effect"] += 1
            else:
                in_window.append((ko, kb, snap))

        kbs = {kb.id: kb for _, kb, _ in in_window}
        kb_perms = await self.access.kb_permissions(user, list(kbs.values()))
        by_kb: dict[str, list[KnowledgeObject]] = defaultdict(list)
        for ko, kb, _ in in_window:
            by_kb[kb.id].append(ko)
        readable: set[str] = set()
        for kb_id, kos in by_kb.items():
            perms = await self.access.resource_permissions(
                user, kos, kb_perms.get(kb_id), RESOURCE_KO
            )
            readable |= {i for i, p in perms.items() if p is not None}
        for ko, kb, snap in in_window:
            if ko.id in readable:
                result.objects[ko.id] = LiveKo(ko, snap, kb)
            else:
                result.dropped["no_access"] += 1
        return result

    async def live_entries(
        self, user: CurrentUser, entry_ids: Sequence[str]
    ) -> tuple[dict[str, LiveEntry], Counter[str]]:
        entries = await self.repo.entries(user.org_id, list(dict.fromkeys(entry_ids)))
        check = await self.live_objects(user, sorted({e.ko_id for e in entries}))
        dropped: Counter[str] = Counter()
        live: dict[str, LiveEntry] = {}
        for entry in entries:
            obj = check.objects.get(entry.ko_id)
            if obj is None:
                dropped["ko_unavailable"] += 1
            elif entry.ko_version != obj.ko.published_version:
                dropped["stale_version"] += 1
            else:
                live[entry.id] = LiveEntry(entry, obj)
        return live, dropped
