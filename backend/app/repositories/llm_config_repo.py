from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LlmModel, LlmProvider, LlmRoute


class LlmConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- providers ----------------------------------------------------------------------

    async def providers(self) -> list[LlmProvider]:
        stmt = select(LlmProvider).order_by(LlmProvider.created_at, LlmProvider.name)
        return list((await self.session.execute(stmt)).scalars())

    async def provider(self, provider_id: str) -> LlmProvider | None:
        return await self.session.get(LlmProvider, provider_id)

    async def provider_by_name(self, name: str) -> LlmProvider | None:
        stmt = select(LlmProvider).where(LlmProvider.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def has_providers(self) -> bool:
        return (await self.session.execute(select(LlmProvider.id).limit(1))).first() is not None

    async def model_counts(self) -> dict[str, int]:
        stmt = select(LlmModel.provider_id, func.count()).group_by(LlmModel.provider_id)
        return {pid: int(n) for pid, n in (await self.session.execute(stmt)).all()}

    # ---- models -------------------------------------------------------------------------

    async def model(self, model_id: str) -> LlmModel | None:
        return await self.session.get(LlmModel, model_id)

    async def models_of(self, provider_id: str) -> list[LlmModel]:
        stmt = select(LlmModel).where(LlmModel.provider_id == provider_id)
        return list((await self.session.execute(stmt)).scalars())

    def models_stmt(
        self, provider_id: str | None, kind: str | None, keyword: str | None
    ) -> Select[LlmModel]:
        stmt = select(LlmModel)
        if provider_id:
            stmt = stmt.where(LlmModel.provider_id == provider_id)
        if kind:
            stmt = stmt.where(LlmModel.kind == kind)
        if keyword:
            stmt = stmt.where(LlmModel.name.ilike(f"%{keyword.strip()}%"))
        return stmt.order_by(LlmModel.kind, LlmModel.name)

    async def find_model(self, name: str, base_urls: list[str]) -> LlmModel | None:
        """A model by name served from one of `base_urls` (its own or its provider's)."""
        stmt = (
            select(LlmModel)
            .join(LlmProvider, LlmProvider.id == LlmModel.provider_id)
            .where(
                LlmModel.name == name,
                or_(
                    LlmModel.base_url.in_(base_urls),
                    LlmModel.base_url.is_(None) & LlmProvider.base_url.in_(base_urls),
                ),
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ---- routes -------------------------------------------------------------------------

    async def routes(self) -> list[LlmRoute]:
        return list((await self.session.execute(select(LlmRoute))).scalars())

    async def route_rows(self) -> list[tuple[LlmRoute, LlmModel, LlmProvider]]:
        stmt = (
            select(LlmRoute, LlmModel, LlmProvider)
            .join(LlmModel, LlmModel.id == LlmRoute.model_id)
            .join(LlmProvider, LlmProvider.id == LlmModel.provider_id)
        )
        return [(r, m, p) for r, m, p in (await self.session.execute(stmt)).all()]

    async def routed_model_ids(self) -> set[str]:
        return set((await self.session.execute(select(LlmRoute.model_id))).scalars())

    async def routed_provider_ids(self) -> set[str]:
        stmt = select(LlmModel.provider_id).join(LlmRoute, LlmRoute.model_id == LlmModel.id)
        return set((await self.session.execute(stmt)).scalars())

    async def clear_route(self, scene: str) -> None:
        await self.session.execute(delete(LlmRoute).where(LlmRoute.scene == scene))
