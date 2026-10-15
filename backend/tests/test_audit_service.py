from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import has_any_permission, has_permission
from app.models import AuditLog
from app.schemas.identity import GroupCreate, GroupUpdate
from app.services.admin.group_service import GroupService
from app.services.audit_service import AuditContext, compute_diff
from app.services.authz import AuthzCache, CurrentUser, Principals
from app.services.context import RequestContext
from tests.factories import make_org


def test_compute_diff() -> None:
    before = {"name": "a", "desc": None, "updated_at": "t1", "same": 1}
    after = {"name": "b", "desc": "x", "updated_at": "t2", "same": 1}
    assert compute_diff(before, after) == {
        "desc": {"before": None, "after": "x"},
        "name": {"before": "a", "after": "b"},
    }
    assert compute_diff(None, {"id": "1"}) == {"id": {"before": None, "after": "1"}}


def test_permission_matching() -> None:
    assert has_permission({"*"}, "admin:user")
    assert has_permission({"admin:*"}, "admin:role")
    assert not has_permission({"admin:*"}, "kb:create")
    assert has_permission({"kb:create"}, "kb:create")
    assert not has_permission({"kb:read"}, "kb:create")
    assert has_any_permission({"kb:read"}, ["admin:user", "kb:read"])


async def test_audited_decorator_records_before_after_and_context(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    actor = CurrentUser(
        id="actor-1",
        org_id=org.id,
        username="alice",
        display_name=None,
        principals=Principals(org.id, "actor-1"),
    )
    state: dict[str, object] = {}
    ctx = RequestContext(
        actor,
        AuditContext(
            org_id=org.id,
            actor_id="actor-1",
            actor_name="alice",
            ip="10.0.0.1",
            trace_id="trace-1",
            method="PUT",
            path="/api/v1/admin/groups/x",
            request_state=state,
        ),
    )
    svc = GroupService(session, ctx, authz_cache)
    group = await svc.create(GroupCreate(name="g1"))
    await svc.update(group.id, GroupUpdate(description="hello"))

    logs = (await session.execute(select(AuditLog).order_by(AuditLog.action))).scalars().all()
    assert [log.action for log in logs] == ["group.create", "group.update"]
    create_log, update_log = logs
    assert create_log.before is None and create_log.after is not None
    assert create_log.resource_id == group.id
    assert update_log.diff == {"description": {"before": None, "after": "hello"}}
    assert (update_log.ip, update_log.trace_id, update_log.actor_name) == (
        "10.0.0.1",
        "trace-1",
        "alice",
    )
    assert state["audit_recorded"] is True
