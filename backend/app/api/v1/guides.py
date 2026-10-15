from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import provide
from app.schemas.guide import GUIDE_KEY_PATTERN, GuideProgressIn, GuideProgressOut
from app.services.guide_service import GuideService

router = APIRouter(prefix="/me/guides", tags=["guides"])

ServiceDep = Annotated[GuideService, Depends(provide(GuideService))]
GuideKey = Annotated[str, Path(pattern=GUIDE_KEY_PATTERN)]


@router.get("", response_model=list[GuideProgressOut])
async def list_progress(service: ServiceDep) -> list[GuideProgressOut]:
    return await service.list_progress()


@router.put("/{guide_key}", response_model=GuideProgressOut)
async def save_progress(
    guide_key: GuideKey, data: GuideProgressIn, service: ServiceDep
) -> GuideProgressOut:
    return await service.save(guide_key, data)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_progress(service: ServiceDep) -> None:
    await service.reset()
