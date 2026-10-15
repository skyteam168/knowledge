from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import GuideStatus

GUIDE_KEY_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"


class GuideProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    guide_key: str
    version: int
    status: GuideStatus
    updated_at: datetime


class GuideProgressIn(BaseModel):
    version: int = Field(ge=1, le=10_000)
    status: GuideStatus = GuideStatus.COMPLETED
