"""Index generations: physical collection/index pairs behind the read aliases (blue-green)."""

import logging
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.llm import EmbeddingSpec
from app.models import GenerationStatus, IndexGeneration
from app.models.base import utcnow
from app.repositories.indexing_repo import IndexGenerationRepository
from app.retrieval.backends import SearchBackends

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexTarget:
    version: int
    qdrant_collection: str
    opensearch_index: str
    embedding: EmbeddingSpec
    status: str

    @classmethod
    def of(cls, gen: IndexGeneration) -> "IndexTarget":
        return cls(
            version=gen.version,
            qdrant_collection=gen.qdrant_collection,
            opensearch_index=gen.opensearch_index,
            embedding=EmbeddingSpec(
                model=gen.embedding_model, dim=gen.embedding_dim, base_url=gen.embedding_base_url
            ),
            status=gen.status,
        )


class GenerationConflictError(Exception):
    pass


class GenerationRegistry:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        backends: SearchBackends,
        settings: Settings,
        default_embedding: EmbeddingSpec,
    ) -> None:
        self.session_factory = session_factory
        self.backends = backends
        self.default_embedding = default_embedding
        self.alias = settings.index_alias
        self._template_ready = False
        self._schema_checked: set[int] = set()

    def physical_names(self, version: int) -> tuple[str, str]:
        name = f"{self.alias}_v{version}"
        return name, name

    async def _ensure_template(self) -> None:
        if not self._template_ready:
            await self.backends.text.ensure_template()
            self._template_ready = True

    async def _ensure_physical(self, target: IndexTarget) -> None:
        await self._ensure_template()
        await self.backends.vector.ensure_collection(target.qdrant_collection, target.embedding.dim)
        await self.backends.text.ensure_index(target.opensearch_index)
        self._schema_checked.add(target.version)

    async def _point_aliases(self, target: IndexTarget) -> None:
        if await self.backends.vector.get_alias(self.alias) != target.qdrant_collection:
            await self.backends.vector.switch_alias(self.alias, target.qdrant_collection)
        if await self.backends.text.get_alias(self.alias) != target.opensearch_index:
            await self.backends.text.switch_alias(self.alias, target.opensearch_index)

    async def generations(self) -> list[IndexGeneration]:
        async with self.session_factory() as session:
            return await IndexGenerationRepository(session).all()

    async def active(self) -> IndexTarget | None:
        async with self.session_factory() as session:
            gens = await IndexGenerationRepository(session).by_status(GenerationStatus.ACTIVE)
        return IndexTarget.of(gens[-1]) if gens else None

    async def write_targets(self) -> list[IndexTarget]:
        """Active generation first, then any generation being built (dual write)."""
        async with self.session_factory() as session:
            gens = await IndexGenerationRepository(session).by_status(
                GenerationStatus.ACTIVE, GenerationStatus.BUILDING
            )
        if not any(g.status == GenerationStatus.ACTIVE.value for g in gens):
            return [await self.bootstrap(), *[IndexTarget.of(g) for g in gens]]
        gens.sort(key=lambda g: (g.status != GenerationStatus.ACTIVE.value, g.version))
        targets = [IndexTarget.of(g) for g in gens]
        for target in targets:
            # Once per process: apply additive schema changes (new fields / payload indexes).
            if target.version not in self._schema_checked:
                await self._ensure_physical(target)
                self._schema_checked.add(target.version)
        return targets

    async def bootstrap(self) -> IndexTarget:
        """Ensure an active generation exists with its collection, index and aliases."""
        target = await self.active()
        if target is None:
            spec = self.default_embedding
            async with self.session_factory() as session:
                version = await IndexGenerationRepository(session).max_version() + 1
                collection, index = self.physical_names(version)
                session.add(
                    IndexGeneration(
                        version=version,
                        qdrant_collection=collection,
                        opensearch_index=index,
                        embedding_model=spec.model,
                        embedding_base_url=spec.base_url,
                        embedding_dim=spec.dim,
                        status=GenerationStatus.ACTIVE.value,
                        stats={},
                        activated_at=utcnow(),
                    )
                )
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
            target = await self.active()
            if target is None:
                raise GenerationConflictError("could not create the initial index generation")
            logger.info("index_generation_bootstrapped", extra={"version": target.version})
        await self._ensure_physical(target)
        await self._point_aliases(target)
        return target

    async def create_building(self, spec: EmbeddingSpec) -> IndexTarget:
        await self.bootstrap()
        async with self.session_factory() as session:
            repo = IndexGenerationRepository(session)
            if await repo.by_status(GenerationStatus.BUILDING):
                raise GenerationConflictError("another index generation is already being built")
            version = await repo.max_version() + 1
            collection, index = self.physical_names(version)
            gen = IndexGeneration(
                version=version,
                qdrant_collection=collection,
                opensearch_index=index,
                embedding_model=spec.model,
                embedding_base_url=spec.base_url,
                embedding_dim=spec.dim,
                status=GenerationStatus.BUILDING.value,
                stats={},
            )
            target = IndexTarget.of(gen)
            # Physical stores first: once the row is visible, writers dual-write into them.
            await self.backends.vector.drop(collection)
            await self.backends.text.drop(index)
            await self._ensure_physical(target)
            session.add(gen)
            await session.commit()
        return target

    async def activate(self, version: int, stats: dict[str, object] | None = None) -> None:
        async with self.session_factory() as session:
            repo = IndexGenerationRepository(session)
            gen = await repo.get_version(version)
            if gen is None:
                raise GenerationConflictError(f"generation {version} not found")
            target = IndexTarget.of(gen)
            await self._ensure_physical(target)
            await self._point_aliases(target)
            now = utcnow()
            for other in await repo.by_status(GenerationStatus.ACTIVE, GenerationStatus.BUILDING):
                if other.version != version:
                    other.status = GenerationStatus.RETIRED.value
                    other.retired_at = now
            gen.status = GenerationStatus.ACTIVE.value
            gen.activated_at = now
            if stats is not None:
                gen.stats = {**gen.stats, **stats}
            await session.commit()
        logger.info("index_generation_activated", extra={"version": version})

    async def mark_failed(self, version: int, error: str) -> None:
        async with self.session_factory() as session:
            gen = await IndexGenerationRepository(session).get_version(version)
            if gen is not None and gen.status == GenerationStatus.BUILDING.value:
                gen.status = GenerationStatus.FAILED.value
                gen.error = error[:2000]
                await session.commit()

    async def drop_physical(self, version: int) -> None:
        async with self.session_factory() as session:
            gen = await IndexGenerationRepository(session).get_version(version)
            if gen is None or gen.status == GenerationStatus.ACTIVE.value:
                raise GenerationConflictError(f"generation {version} is active or missing")
            await self.backends.vector.drop(gen.qdrant_collection)
            await self.backends.text.drop(gen.opensearch_index)
