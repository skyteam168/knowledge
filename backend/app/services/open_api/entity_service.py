"""Open-platform entity.read / graph.traverse helpers (shared by REST and MCP)."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import TerminologyEntity, TerminologyRelation
from app.repositories.structured_repo import StructuredRepository
from app.repositories.terminology_repo import TerminologyRepository
from app.retrieval.graph import traverse_ko_relations
from app.schemas.open_api import (
    OpenEntityKoOut,
    OpenEntityMirrorOut,
    OpenEntityReadIn,
    OpenEntityReadOut,
    OpenEntityTermOut,
    OpenGraphNeighborOut,
    OpenGraphSeedOut,
    OpenGraphTraverseIn,
    OpenGraphTraverseOut,
    OpenRelatedTermOut,
)
from app.services.authz import AuthzCache, CurrentUser
from app.services.context import RequestContext
from app.services.knowledge.ko_access import KoAccess
from app.services.open_api.auth import ApiCaller
from app.services.structured.service import StructuredService
from app.services.terminology.expander import normalize_alias


class OpenEntityService:
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        caller: ApiCaller,
    ) -> None:
        self.session = session
        self.ctx = ctx
        self.authz_cache = authz_cache
        self.caller = caller
        self.terms = TerminologyRepository(session)
        self.structured = StructuredRepository(session)
        self.kos = KoAccess(session)

    @property
    def org_id(self) -> str:
        return self.ctx.user.org_id

    @property
    def user(self) -> CurrentUser:
        return self.ctx.user

    def _kb_bound(self, requested: list[str]) -> frozenset[str]:
        if not self.caller.kb_ids:
            return frozenset()
        if not requested:
            return self.caller.kb_ids
        return self.caller.kb_ids & frozenset(requested)

    async def _term_out(self, entity: TerminologyEntity) -> OpenEntityTermOut:
        aliases = await self.terms.list_aliases_for(self.org_id, [entity.id])
        return OpenEntityTermOut(
            id=entity.id,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            status=entity.status,
            aliases=[a.alias for a in aliases],
        )

    async def _related_terms(self, entity_id: str) -> list[OpenRelatedTermOut]:
        edges = list(
            await self.session.scalars(
                select(TerminologyRelation).where(
                    TerminologyRelation.org_id == self.org_id,
                    or_(
                        TerminologyRelation.from_id == entity_id,
                        TerminologyRelation.to_id == entity_id,
                    ),
                )
            )
        )
        if not edges:
            return []
        peer_ids = {
            (e.to_id if e.from_id == entity_id else e.from_id) for e in edges
        }
        peers = {
            row.id: row
            for row in await self.session.scalars(
                select(TerminologyEntity).where(
                    TerminologyEntity.org_id == self.org_id,
                    TerminologyEntity.id.in_(peer_ids),
                )
            )
        }
        out: list[OpenRelatedTermOut] = []
        for edge in edges:
            if edge.from_id == entity_id:
                peer = peers.get(edge.to_id)
                direction = "out"
            else:
                peer = peers.get(edge.from_id)
                direction = "in"
            if peer is None:
                continue
            out.append(
                OpenRelatedTermOut(
                    id=peer.id,
                    canonical_name=peer.canonical_name,
                    entity_type=peer.entity_type,
                    kind=edge.kind,
                    direction=direction,
                )
            )
        return out

    async def _filter_kos(self, ko_ids: list[str], *, kb_bound: frozenset[str]) -> list[OpenEntityKoOut]:
        if not ko_ids or not kb_bound:
            return []
        check = await self.kos.live_objects(self.user, ko_ids)
        out: list[OpenEntityKoOut] = []
        seen: set[str] = set()
        for kid in ko_ids:
            if kid in seen:
                continue
            live = check.objects.get(kid)
            if live is None or live.kb.id not in kb_bound:
                continue
            seen.add(kid)
            out.append(
                OpenEntityKoOut(
                    id=live.ko.id,
                    title=live.ko.title,
                    ko_type=live.ko.ko_type,
                    kb_id=live.kb.id,
                )
            )
        return out

    async def _resolve_term(self, data: OpenEntityReadIn) -> TerminologyEntity:
        if data.entity_id:
            entity = await self.terms.get_entity(self.org_id, data.entity_id)
            if entity is None:
                raise NotFoundError("Terminology entity not found")
            return entity
        assert data.name is not None
        alias = await self.terms.find_alias_normalized(self.org_id, normalize_alias(data.name))
        if alias is not None:
            entity = await self.terms.get_entity(self.org_id, alias.entity_id)
            if entity is not None:
                return entity
        entity = await self.terms.get_entity_by_canonical(self.org_id, data.name)
        if entity is None:
            raise NotFoundError("Terminology entity not found")
        return entity

    async def entity_read(self, data: OpenEntityReadIn) -> OpenEntityReadOut:
        kb_bound = self._kb_bound([])
        if data.object_type and data.external_id:
            structured = StructuredService(self.session, self.ctx, self.authz_cache)
            resolved = await structured.resolve(
                data.object_type, data.external_id, source_id=data.source_id
            )
            mirror = OpenEntityMirrorOut(
                object_type=resolved.object_type,
                object_id=resolved.object_id,
                external_id=resolved.external_id,
                source_id=resolved.source_id,
                label=resolved.label,
                status=resolved.status,
            )
            terminology: OpenEntityTermOut | None = None
            term_ids = [
                link.terminology_entity_id
                for link in resolved.links
                if link.terminology_entity_id
            ]
            if term_ids:
                entity = await self.terms.get_entity(self.org_id, term_ids[0])
                if entity is not None:
                    terminology = await self._term_out(entity)
            ko_ids = [link.ko_id for link in resolved.links if link.ko_id]
            related: list[OpenRelatedTermOut] = []
            if terminology is not None:
                related = await self._related_terms(terminology.id)
            return OpenEntityReadOut(
                terminology=terminology,
                mirror=mirror,
                knowledge_objects=await self._filter_kos(ko_ids, kb_bound=kb_bound),
                related_terms=related,
            )

        entity = await self._resolve_term(data)
        links = await self.structured.list_links_for_term(self.org_id, entity.id)
        ko_ids = [link.ko_id for link in links if link.ko_id]
        return OpenEntityReadOut(
            terminology=await self._term_out(entity),
            mirror=None,
            knowledge_objects=await self._filter_kos(ko_ids, kb_bound=kb_bound),
            related_terms=await self._related_terms(entity.id),
        )

    async def graph_traverse(self, data: OpenGraphTraverseIn) -> OpenGraphTraverseOut:
        kb_bound = self._kb_bound(data.kb_ids)
        if not kb_bound:
            raise NotFoundError("Knowledge object not found")

        seed_check = await self.kos.live_objects(self.user, [data.ko_id])
        seed_live = seed_check.objects.get(data.ko_id)
        if seed_live is None or seed_live.kb.id not in kb_bound:
            raise NotFoundError("Knowledge object not found")

        neighbors = await traverse_ko_relations(
            self.session,
            self.org_id,
            [data.ko_id],
            max_hops=data.max_hops,
            limit=40,
            kb_ids=sorted(kb_bound),
            relation_types=data.relation_types or None,
            direction=data.direction,
        )
        check = await self.kos.live_objects(self.user, [n.ko_id for n in neighbors])
        out_neighbors: list[OpenGraphNeighborOut] = []
        for n in neighbors:
            live = check.objects.get(n.ko_id)
            if live is None or live.kb.id not in kb_bound:
                continue
            out_neighbors.append(
                OpenGraphNeighborOut(
                    ko_id=live.ko.id,
                    title=live.ko.title,
                    hops=n.hops,
                    seed_id=n.seed_ko_id,
                    ko_type=live.ko.ko_type,
                    kb_id=live.kb.id,
                    path=n.path,
                )
            )

        seed = seed_live.ko
        return OpenGraphTraverseOut(
            seed=OpenGraphSeedOut(
                id=seed.id,
                title=seed.title,
                ko_type=seed.ko_type,
                kb_id=seed_live.kb.id,
            ),
            neighbors=out_neighbors,
            max_hops=data.max_hops,
            direction=data.direction,
        )
