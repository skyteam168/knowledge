from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_id: str | None
    actor_name: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    diff: dict[str, Any] | None
    ip: str | None
    user_agent: str | None
    trace_id: str | None
    method: str | None
    path: str | None
    status_code: int | None
    created_at: datetime
