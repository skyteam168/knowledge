import logging
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models import RetrievalProfile
from app.repositories.search_repo import RetrievalProfileRepository
from app.retrieval.config import RetrievalConfig
from app.schemas.search import (
    RetrievalProfileCreate,
    RetrievalProfileOut,
    RetrievalProfileUpdate,
)
from app.services.authz import AuthzCache
from app.services.context import BaseService, RequestContext

logger = logging.getLogger(__name__)

RESOURCE_PROFILE = "retrieval_profile"
BUILTIN_NAME = "builtin"


@dataclass(frozen=True)
class ResolvedProfile:
    id: str | None
    name: str
    config: RetrievalConfig


def load_config(profile: RetrievalProfile, fallback: RetrievalConfig) -> RetrievalConfig:
    try:
        return RetrievalConfig.model_validate(profile.config)
    except ValidationError:
        logger.warning("retrieval_profile_invalid", extra={"profile_id": profile.id})
        return fallback


def _snapshot(profile: RetrievalProfile) -> dict[str, object]:
    return {
        "name": profile.name,
        "description": profile.description,
        "config": profile.config,
        "is_active": profile.is_active,
    }


class RetrievalProfileService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        settings: Settings,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.repo = RetrievalProfileRepository(session)
        self.builtin = RetrievalConfig.from_settings(settings)

    def _builtin_out(self, active: bool) -> RetrievalProfileOut:
        return RetrievalProfileOut(
            id=None,
            name=BUILTIN_NAME,
            description="内置默认策略（来自服务配置）",
            config=self.builtin,
            is_active=active,
            builtin=True,
        )

    def _out(self, profile: RetrievalProfile) -> RetrievalProfileOut:
        return RetrievalProfileOut(
            id=profile.id,
            name=profile.name,
            description=profile.description,
            config=load_config(profile, self.builtin),
            is_active=profile.is_active,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    async def _get(self, profile_id: str) -> RetrievalProfile:
        profile = await self.repo.get(self.org_id, profile_id)
        if profile is None:
            raise NotFoundError("Retrieval profile not found")
        return profile

    async def _ensure_unique(self, name: str, exclude_id: str | None = None) -> None:
        if name == BUILTIN_NAME:
            raise ConflictError(f"'{BUILTIN_NAME}' is reserved")
        existing = await self.repo.get_by_name(self.org_id, name)
        if existing is not None and existing.id != exclude_id:
            raise ConflictError("A profile with this name already exists")

    async def list(self) -> list[RetrievalProfileOut]:
        profiles = await self.repo.list(self.org_id)
        active = any(p.is_active for p in profiles)
        return [self._builtin_out(not active), *(self._out(p) for p in profiles)]

    async def builtin_config(self) -> RetrievalConfig:
        return self.builtin

    async def resolve(self, profile_id: str | None = None) -> ResolvedProfile:
        """The requested profile (A/B, debugging) or the org's active one, else built-in."""
        if profile_id == BUILTIN_NAME:
            return ResolvedProfile(None, BUILTIN_NAME, self.builtin)
        profile = await self._get(profile_id) if profile_id else await self.repo.active(self.org_id)
        if profile is None:
            return ResolvedProfile(None, BUILTIN_NAME, self.builtin)
        return ResolvedProfile(profile.id, profile.name, load_config(profile, self.builtin))

    async def create(self, data: RetrievalProfileCreate) -> RetrievalProfileOut:
        await self._ensure_unique(data.name)
        profile = RetrievalProfile(
            org_id=self.org_id,
            name=data.name,
            description=data.description,
            config=data.config.model_dump(mode="json"),
            is_active=False,
            created_by=self.ctx.user.id,
            updated_by=self.ctx.user.id,
        )
        self.session.add(profile)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "retrieval_profile.create",
            RESOURCE_PROFILE,
            profile.id,
            None,
            _snapshot(profile),
        )
        return self._out(profile)

    async def update(self, profile_id: str, data: RetrievalProfileUpdate) -> RetrievalProfileOut:
        profile = await self._get(profile_id)
        before = _snapshot(profile)
        if data.name is not None and data.name != profile.name:
            await self._ensure_unique(data.name, exclude_id=profile.id)
            profile.name = data.name
        if "description" in data.model_fields_set:
            profile.description = data.description
        if data.config is not None:
            profile.config = data.config.model_dump(mode="json")
        profile.updated_by = self.ctx.user.id
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "retrieval_profile.update",
            RESOURCE_PROFILE,
            profile.id,
            before,
            _snapshot(profile),
        )
        return self._out(profile)

    async def delete(self, profile_id: str) -> None:
        profile = await self._get(profile_id)
        if profile.is_active:
            raise ConflictError("The active profile cannot be deleted; activate another first")
        before = _snapshot(profile)
        await self.session.delete(profile)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "retrieval_profile.delete", RESOURCE_PROFILE, profile_id, before, None
        )

    async def activate(self, profile_id: str) -> RetrievalProfileOut:
        """Make `profile_id` the org's active profile (`builtin` reverts to the defaults)."""
        previous = await self.repo.active(self.org_id)
        if profile_id == BUILTIN_NAME:
            await self.repo.deactivate_all(self.org_id)
            result = self._builtin_out(True)
        else:
            profile = await self._get(profile_id)
            await self.repo.deactivate_all(self.org_id)
            profile.is_active = True
            await self.session.flush()
            result = self._out(profile)
        await self.audit.record(
            self.audit_ctx,
            "retrieval_profile.activate",
            RESOURCE_PROFILE,
            result.id or BUILTIN_NAME,
            {"active": previous.name if previous else BUILTIN_NAME},
            {"active": result.name},
        )
        return result
