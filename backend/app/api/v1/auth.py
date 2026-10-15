from fastapi import APIRouter

from app.api.deps import CurrentUserDep, DbSessionDep
from app.schemas.identity import MeResponse
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUserDep, session: DbSessionDep) -> MeResponse:
    return await ProfileService(session).me(user)
