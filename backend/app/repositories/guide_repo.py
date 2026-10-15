from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserGuideProgress


class GuideRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for(self, org_id: str, user_id: str) -> list[UserGuideProgress]:
        stmt = (
            select(UserGuideProgress)
            .where(UserGuideProgress.org_id == org_id, UserGuideProgress.user_id == user_id)
            .order_by(UserGuideProgress.guide_key)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get(self, org_id: str, user_id: str, guide_key: str) -> UserGuideProgress | None:
        stmt = select(UserGuideProgress).where(
            UserGuideProgress.org_id == org_id,
            UserGuideProgress.user_id == user_id,
            UserGuideProgress.guide_key == guide_key,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def delete_for(self, org_id: str, user_id: str) -> int:
        result = await self.session.execute(
            delete(UserGuideProgress).where(
                UserGuideProgress.org_id == org_id, UserGuideProgress.user_id == user_id
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)
