from sqlalchemy.exc import IntegrityError

from app.models import UserGuideProgress
from app.models.base import utcnow
from app.repositories.guide_repo import GuideRepository
from app.schemas.guide import GuideProgressIn, GuideProgressOut
from app.services.context import BaseService


class GuideService(BaseService):
    """The caller's own onboarding progress. Personal UI state, so writes are not audited."""

    @property
    def repo(self) -> GuideRepository:
        return GuideRepository(self.session)

    @property
    def user_id(self) -> str:
        return self.ctx.user.id

    async def list_progress(self) -> list[GuideProgressOut]:
        rows = await self.repo.list_for(self.org_id, self.user_id)
        return [GuideProgressOut.model_validate(r) for r in rows]

    async def save(self, guide_key: str, data: GuideProgressIn) -> GuideProgressOut:
        row = await self.repo.get(self.org_id, self.user_id, guide_key)
        if row is None:
            row = UserGuideProgress(
                org_id=self.org_id,
                user_id=self.user_id,
                guide_key=guide_key,
                version=data.version,
                status=data.status,
                updated_at=utcnow(),
            )
            self.session.add(row)
            try:
                await self.session.flush()
            except IntegrityError:
                # Two tabs finishing the same tour at once: keep the row the other one wrote.
                await self.session.rollback()
                row = await self.repo.get(self.org_id, self.user_id, guide_key)
                if row is None:
                    raise
        row.version = data.version
        row.status = data.status
        row.updated_at = utcnow()
        await self.session.commit()
        return GuideProgressOut.model_validate(row)

    async def reset(self) -> int:
        removed = await self.repo.delete_for(self.org_id, self.user_id)
        await self.session.commit()
        return removed
