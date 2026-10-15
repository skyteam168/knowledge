from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSessionDep, RequestContextDep, require_permission
from app.repositories.audit_repo import AuditQuery
from app.schemas.audit import AuditLogOut
from app.schemas.common import Page
from app.services.audit_service import AuditService

router = APIRouter(prefix="/admin/audit-logs", tags=["admin:audit"])


@router.get(
    "",
    response_model=Page[AuditLogOut],
    dependencies=[Depends(require_permission("admin:audit"))],
)
async def search_audit_logs(
    ctx: RequestContextDep,
    session: DbSessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    actor_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    trace_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Page[AuditLogOut]:
    query = AuditQuery(actor_id, action, resource_type, resource_id, trace_id, start, end)
    logs, total = await AuditService(session).search(ctx.org_id, query, page, size)
    return Page(
        items=[AuditLogOut.model_validate(log) for log in logs], total=total, page=page, size=size
    )
