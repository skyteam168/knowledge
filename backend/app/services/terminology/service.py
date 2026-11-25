from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models import (
    TerminologyAlias,
    TerminologyEntity,
    TerminologyEntityType,
    TerminologyLang,
    TerminologyRelation,
    TerminologyRelationKind,
    TerminologyStatus,
)
from app.repositories.terminology_repo import TerminologyRepository
from app.schemas.common import Page
from app.schemas.terminology import (
    ConceptGraphEdge,
    ConceptGraphNode,
    TerminologyAliasCreate,
    TerminologyAliasOut,
    TerminologyEntityCreate,
    TerminologyEntityOut,
    TerminologyEntityUpdate,
    TerminologyNeighborhoodOut,
    TerminologyRelationCreate,
    TerminologyRelationOut,
    TerminologySynonymsSyncOut,
)
from app.services.authz.cache import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.indexing.runtime import IndexingRuntime
from app.services.terminology.expander import (
    AliasEntry,
    QueryExpansion,
    expand_queries,
    merge_search_text,
    normalize_alias,
)
from app.services.terminology.synonyms import format_synonym_lines, write_synonyms_file

RESOURCE_ENTITY = "terminology_entity"
RESOURCE_ALIAS = "terminology_alias"

_ENTITY_TYPES = {t.value for t in TerminologyEntityType}
_STATUSES = {s.value for s in TerminologyStatus}
_LANGS = {lang.value for lang in TerminologyLang}
_RELATION_KINDS = {k.value for k in TerminologyRelationKind}
RESOURCE_RELATION = "terminology_relation"


class TerminologyService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        settings: Settings,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.settings = settings
        self.repo = TerminologyRepository(session)

    def _out(
        self, entity: TerminologyEntity, aliases: Sequence[TerminologyAlias]
    ) -> TerminologyEntityOut:
        return TerminologyEntityOut(
            id=entity.id,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            description=entity.description,
            status=entity.status,
            aliases=[
                TerminologyAliasOut(
                    id=a.id,
                    entity_id=a.entity_id,
                    alias=a.alias,
                    lang=a.lang,
                    created_at=a.created_at,
                )
                for a in aliases
            ],
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    async def list_entities(
        self,
        *,
        page: int = 1,
        size: int = 20,
        q: str | None = None,
        entity_type: str | None = None,
        status: str | None = None,
    ) -> Page[TerminologyEntityOut]:
        items, total = await self.repo.list_entities(
            self.org_id, page=page, size=size, q=q, entity_type=entity_type, status=status
        )
        aliases = await self.repo.list_aliases_for(self.org_id, [e.id for e in items])
        by_id: dict[str, list[TerminologyAlias]] = {e.id: [] for e in items}
        for alias in aliases:
            by_id.setdefault(alias.entity_id, []).append(alias)
        return Page(
            items=[self._out(e, by_id.get(e.id, [])) for e in items],
            total=total,
            page=page,
            size=size,
        )

    async def get_entity(self, entity_id: str) -> TerminologyEntityOut:
        entity = await self.repo.get_entity(self.org_id, entity_id)
        if entity is None:
            raise NotFoundError("Terminology entity not found")
        aliases = await self.repo.list_aliases_for(self.org_id, [entity.id])
        return self._out(entity, aliases)

    def _validate_type(self, entity_type: str) -> str:
        if entity_type not in _ENTITY_TYPES:
            raise ValidationAppError(
                "Unknown entity_type", detail={"allowed": sorted(_ENTITY_TYPES)}
            )
        return entity_type

    def _validate_status(self, status: str) -> str:
        if status not in _STATUSES:
            raise ValidationAppError("Unknown status", detail={"allowed": sorted(_STATUSES)})
        return status

    def _validate_lang(self, lang: str) -> str:
        if lang not in _LANGS:
            raise ValidationAppError("Unknown lang", detail={"allowed": sorted(_LANGS)})
        return lang

    async def add_relation(
        self, data: TerminologyRelationCreate
    ) -> TerminologyRelationOut:
        kind = data.kind.strip().lower()
        if kind not in _RELATION_KINDS:
            raise ValidationAppError(
                "Invalid terminology relation kind",
                detail={"allowed": sorted(_RELATION_KINDS)},
            )
        from_id = data.from_id.strip()
        to_id = data.to_id.strip()
        if from_id == to_id:
            raise ValidationAppError("Self-loop terminology relations are not allowed")
        for eid, side in ((from_id, "from"), (to_id, "to")):
            entity = await self.repo.get_entity(self.org_id, eid)
            if entity is None:
                raise NotFoundError(f"{side} terminology entity not found")
        existing = await self.session.scalar(
            select(TerminologyRelation).where(
                TerminologyRelation.org_id == self.org_id,
                TerminologyRelation.from_id == from_id,
                TerminologyRelation.to_id == to_id,
                TerminologyRelation.kind == kind,
            )
        )
        if existing is not None:
            raise ConflictError("Terminology relation already exists")
        row = TerminologyRelation(
            org_id=self.org_id,
            from_id=from_id,
            to_id=to_id,
            kind=kind,
            created_by=self.ctx.user.id,
        )
        self.session.add(row)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "terminology.relation.create",
            RESOURCE_RELATION,
            row.id,
            None,
            {"from_id": from_id, "to_id": to_id, "kind": kind},
        )
        return TerminologyRelationOut(
            id=row.id,
            from_id=row.from_id,
            to_id=row.to_id,
            kind=row.kind,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_relations(
        self, entity_id: str
    ) -> list[TerminologyRelationOut]:
        entity = await self.repo.get_entity(self.org_id, entity_id)
        if entity is None:
            raise NotFoundError("Terminology entity not found")
        rows = await self.session.scalars(
            select(TerminologyRelation)
            .where(
                TerminologyRelation.org_id == self.org_id,
                or_(
                    TerminologyRelation.from_id == entity_id,
                    TerminologyRelation.to_id == entity_id,
                ),
            )
            .order_by(TerminologyRelation.kind, TerminologyRelation.id)
        )
        return [
            TerminologyRelationOut(
                id=r.id,
                from_id=r.from_id,
                to_id=r.to_id,
                kind=r.kind,
                created_by=r.created_by,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    async def create_entity(self, data: TerminologyEntityCreate) -> TerminologyEntityOut:
        entity = TerminologyEntity(
            org_id=self.org_id,
            canonical_name=data.canonical_name.strip(),
            entity_type=self._validate_type(data.entity_type),
            description=(data.description.strip() if data.description else None),
            status=self._validate_status(data.status),
        )
        self.repo.add(entity)
        await self.session.flush()
        created_aliases: list[TerminologyAlias] = []
        # Ensure canonical is also an alias so expansion matches both directions.
        forms = [entity.canonical_name, *[a.strip() for a in data.aliases if a.strip()]]
        seen: set[str] = set()
        for form in forms:
            norm = normalize_alias(form)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            alias = TerminologyAlias(
                org_id=self.org_id,
                entity_id=entity.id,
                alias=form,
                alias_normalized=norm,
                lang=TerminologyLang.ANY.value,
            )
            self.repo.add(alias)
            created_aliases.append(alias)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise ConflictError("Alias already exists in this organization") from exc
        await self.audit.record(
            self.audit_ctx,
            "terminology.create",
            RESOURCE_ENTITY,
            entity.id,
            None,
            {"canonical_name": entity.canonical_name, "entity_type": entity.entity_type},
        )
        await self.session.commit()
        return self._out(entity, created_aliases)

    async def update_entity(
        self, entity_id: str, data: TerminologyEntityUpdate
    ) -> TerminologyEntityOut:
        entity = await self.repo.get_entity(self.org_id, entity_id)
        if entity is None:
            raise NotFoundError("Terminology entity not found")
        before = {
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type,
            "status": entity.status,
        }
        if data.canonical_name is not None:
            entity.canonical_name = data.canonical_name.strip()
        if data.entity_type is not None:
            entity.entity_type = self._validate_type(data.entity_type)
        if data.description is not None:
            entity.description = data.description.strip() or None
        if data.status is not None:
            entity.status = self._validate_status(data.status)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "terminology.update",
            RESOURCE_ENTITY,
            entity.id,
            before,
            {
                "canonical_name": entity.canonical_name,
                "entity_type": entity.entity_type,
                "status": entity.status,
            },
        )
        await self.session.commit()
        aliases = await self.repo.list_aliases_for(self.org_id, [entity.id])
        return self._out(entity, aliases)

    async def delete_entity(self, entity_id: str) -> None:
        entity = await self.repo.get_entity(self.org_id, entity_id)
        if entity is None:
            raise NotFoundError("Terminology entity not found")
        before = {"canonical_name": entity.canonical_name}
        await self.repo.delete_entity(entity)
        await self.audit.record(
            self.audit_ctx, "terminology.delete", RESOURCE_ENTITY, entity_id, before, None
        )
        await self.session.commit()

    async def add_alias(
        self, entity_id: str, data: TerminologyAliasCreate
    ) -> TerminologyAliasOut:
        entity = await self.repo.get_entity(self.org_id, entity_id)
        if entity is None:
            raise NotFoundError("Terminology entity not found")
        form = data.alias.strip()
        norm = normalize_alias(form)
        if not norm:
            raise ValidationAppError("Alias is empty")
        existing = await self.repo.find_alias_normalized(self.org_id, norm)
        if existing is not None:
            raise ConflictError("Alias already exists in this organization")
        alias = TerminologyAlias(
            org_id=self.org_id,
            entity_id=entity.id,
            alias=form,
            alias_normalized=norm,
            lang=self._validate_lang(data.lang),
        )
        self.repo.add(alias)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise ConflictError("Alias already exists in this organization") from exc
        await self.audit.record(
            self.audit_ctx,
            "terminology.alias_create",
            RESOURCE_ALIAS,
            alias.id,
            None,
            {"entity_id": entity_id, "alias": form},
        )
        await self.session.commit()
        return TerminologyAliasOut(
            id=alias.id,
            entity_id=alias.entity_id,
            alias=alias.alias,
            lang=alias.lang,
            created_at=alias.created_at,
        )

    async def delete_alias(self, alias_id: str) -> None:
        alias = await self.repo.get_alias(self.org_id, alias_id)
        if alias is None:
            raise NotFoundError("Terminology alias not found")
        before = {"alias": alias.alias, "entity_id": alias.entity_id}
        await self.repo.delete_alias(alias)
        await self.audit.record(
            self.audit_ctx, "terminology.alias_delete", RESOURCE_ALIAS, alias_id, before, None
        )
        await self.session.commit()

    async def _alias_entries(self) -> list[AliasEntry]:
        rows = await self.repo.load_active_alias_map(self.org_id)
        entries: list[AliasEntry] = []
        for entity, aliases in rows:
            forms = [entity.canonical_name, *[a.alias for a in aliases]]
            entries.append(
                AliasEntry(
                    entity_id=entity.id,
                    canonical_name=entity.canonical_name,
                    forms=tuple(dict.fromkeys(f for f in forms if f.strip())),
                )
            )
        return entries

    async def expand_for_org(self, texts: Sequence[str]) -> QueryExpansion:
        if not self.settings.terminology_expand_enabled:
            return QueryExpansion(original=list(texts), queries=list(texts))
        entries = await self._alias_entries()
        return expand_queries(
            list(texts),
            entries,
            max_extra=max(0, self.settings.terminology_expand_max_extra),
        )

    async def expand_search_text(self, text: str) -> tuple[str, QueryExpansion]:
        expansion = await self.expand_for_org([text])
        return merge_search_text(text, expansion), expansion

    async def neighborhood(self, entity_id: str) -> TerminologyNeighborhoodOut:
        """Term ↔ structured mirrors ↔ linked KOs (+ 1-hop KO neighbors) for admin preview."""
        from app.models import EquipDevice, EquipSparePart, EquipWorkOrder, StructuredObjectType
        from app.repositories.structured_repo import StructuredRepository
        from app.retrieval.graph import traverse_ko_relations
        from app.services.knowledge.ko_access import KoAccess

        entity_out = await self.get_entity(entity_id)
        structured = StructuredRepository(self.session)
        links = await structured.list_links_for_term(self.org_id, entity_id)

        nodes: dict[str, ConceptGraphNode] = {
            f"term:{entity_id}": ConceptGraphNode(
                id=f"term:{entity_id}",
                label=entity_out.canonical_name,
                kind="term",
                meta={"entity_type": entity_out.entity_type},
            )
        }
        edges: list[ConceptGraphEdge] = []
        ko_ids: list[str] = []

        for link in links:
            mid = f"mirror:{link.object_type}:{link.object_id}"
            label = link.object_id
            external_id = ""
            if link.object_type == StructuredObjectType.DEVICE.value:
                row = await self.session.get(EquipDevice, link.object_id)
                if row and row.org_id == self.org_id:
                    label, external_id = row.name, row.external_id
            elif link.object_type == StructuredObjectType.WORK_ORDER.value:
                row = await self.session.get(EquipWorkOrder, link.object_id)
                if row and row.org_id == self.org_id:
                    label, external_id = row.title, row.external_id
            elif link.object_type == StructuredObjectType.SPARE_PART.value:
                row = await self.session.get(EquipSparePart, link.object_id)
                if row and row.org_id == self.org_id:
                    label, external_id = row.name, row.external_id
            if mid not in nodes:
                nodes[mid] = ConceptGraphNode(
                    id=mid,
                    label=label,
                    kind="mirror",
                    meta={
                        "object_type": link.object_type,
                        "external_id": external_id or link.object_id,
                    },
                )
                edges.append(
                    ConceptGraphEdge(
                        source=f"term:{entity_id}", target=mid, relation="maps_to"
                    )
                )
            if link.ko_id:
                ko_ids.append(link.ko_id)

        kos = KoAccess(self.session)
        live = await kos.live_objects(self.ctx.user, list(dict.fromkeys(ko_ids)))
        seed_ko_ids: list[str] = []
        for kid in dict.fromkeys(ko_ids):
            obj = live.objects.get(kid)
            if obj is None:
                continue
            nid = f"ko:{kid}"
            seed_ko_ids.append(kid)
            if nid not in nodes:
                nodes[nid] = ConceptGraphNode(
                    id=nid,
                    label=obj.ko.title,
                    kind="ko",
                    meta={"ko_type": obj.ko.ko_type, "kb_id": obj.kb.id},
                )
            # Attach KO to term (and to mirrors that pointed here).
            edges.append(
                ConceptGraphEdge(source=f"term:{entity_id}", target=nid, relation="linked")
            )
            for link in links:
                if link.ko_id == kid:
                    mid = f"mirror:{link.object_type}:{link.object_id}"
                    if mid in nodes:
                        edges.append(
                            ConceptGraphEdge(source=mid, target=nid, relation="documents")
                        )

        if seed_ko_ids and len(nodes) < 20:
            neighbors = await traverse_ko_relations(
                self.session,
                self.org_id,
                seed_ko_ids,
                max_hops=1,
                limit=max(1, 20 - len(nodes)),
            )
            n_live = await kos.live_objects(self.ctx.user, [n.ko_id for n in neighbors])
            for n in neighbors:
                if len(nodes) >= 20:
                    break
                obj = n_live.objects.get(n.ko_id)
                if obj is None:
                    continue
                nid = f"ko:{n.ko_id}"
                if nid not in nodes:
                    nodes[nid] = ConceptGraphNode(
                        id=nid,
                        label=obj.ko.title,
                        kind="ko",
                        meta={"ko_type": obj.ko.ko_type, "kb_id": obj.kb.id, "hops": "1"},
                    )
                edges.append(
                    ConceptGraphEdge(
                        source=f"ko:{n.seed_ko_id}",
                        target=nid,
                        relation="related",
                    )
                )

        # Deduplicate edges.
        seen_e: set[tuple[str, str, str]] = set()
        uniq_edges: list[ConceptGraphEdge] = []
        for e in edges:
            key = (e.source, e.target, e.relation)
            if key in seen_e:
                continue
            seen_e.add(key)
            uniq_edges.append(e)

        return TerminologyNeighborhoodOut(
            entity=entity_out,
            nodes=list(nodes.values()),
            edges=uniq_edges,
        )

    async def sync_opensearch_synonyms(
        self,
        *,
        path: Path | None = None,
        reload: bool | None = None,
        runtime: IndexingRuntime | None = None,
    ) -> TerminologySynonymsSyncOut:
        """Export active aliases into synonyms.txt and optionally reload analyzers."""
        target = path or (
            Path(self.settings.opensearch_synonyms_file)
            if self.settings.opensearch_synonyms_file
            else None
        )
        if target is None:
            raise ValidationAppError(
                "OPENSEARCH_SYNONYMS_FILE is not configured; cannot write synonyms"
            )
        rows = await self.repo.load_active_alias_map(self.org_id)
        lines = format_synonym_lines(rows)
        count = write_synonyms_file(target, lines)
        do_reload = self.settings.terminology_synonyms_reload if reload is None else reload
        reloaded = False
        if do_reload:
            if runtime is None:
                raise ValidationAppError("indexing runtime required to reload synonyms")
            active = await runtime.registry.active() or await runtime.registry.bootstrap()
            await runtime.backends.text.reload_search_analyzers(active.opensearch_index)
            reloaded = True
        await self.audit.record(
            self.audit_ctx,
            "terminology.sync_synonyms",
            RESOURCE_ENTITY,
            self.org_id,
            None,
            {"path": str(target), "lines": count, "reloaded": reloaded},
        )
        return TerminologySynonymsSyncOut(path=str(target), lines=count, reloaded=reloaded)
