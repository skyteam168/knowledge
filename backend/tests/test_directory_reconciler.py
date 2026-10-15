from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Department,
    Group,
    User,
    UserDepartment,
    UserGroup,
    UserIdentity,
)
from app.models.base import new_id
from app.repositories.org_repo import DepartmentRepository
from app.services.authz import AuthzCache
from app.services.authz.principals import PrincipalResolver
from app.services.directory.reconciler import DirectoryReconciler, SyncOptions
from app.services.directory.snapshot import DeptRecord, Snapshot, UserRecord

ORG = "org-dir"


def opts(**kw: object) -> SyncOptions:
    base: dict[str, object] = {"source_type": "wecom", "is_primary": True}
    base.update(kw)
    return SyncOptions(**base)  # type: ignore[arg-type]


def group_snapshot(**overrides: object) -> Snapshot:
    depts = [
        DeptRecord("1", "集团"),
        DeptRecord("10", "越南Flyknit", "1"),
        DeptRecord("11", "织造车间", "10"),
        DeptRecord("12", "品质部", "10"),
        DeptRecord("20", "总部", "1"),
        DeptRecord("21", "法务部", "20"),
        DeptRecord("30", "印尼工厂", "1"),
        DeptRecord("31", "织造车间", "30"),
    ]
    users = [
        UserRecord(
            "u1",
            "zhangsan",
            "张三",
            employee_no="VN001",
            title="班组长",
            dept_external_ids=["11", "12"],
            primary_dept="11",
        ),
        UserRecord(
            "u2", "lisi", "李四", mobile="13800000000", title="法务专员", dept_external_ids=["21"]
        ),
        UserRecord("u3", "wangwu", "王五", email="ww@example.com", dept_external_ids=["31"]),
    ]
    snap = Snapshot(departments=depts, users=users)
    for key, value in overrides.items():
        setattr(snap, key, value)
    return snap


async def run(session: AsyncSession, snap: Snapshot, apply: bool = True, **kw: object):  # type: ignore[no-untyped-def]
    result = await DirectoryReconciler(session, ORG).run(snap, opts(**kw), apply=apply)
    await session.commit()
    return result


async def dept_by_ext(session: AsyncSession, ext: str) -> Department:
    return (
        await session.execute(
            select(Department).where(Department.org_id == ORG, Department.external_id == ext)
        )
    ).scalar_one()


async def user_by_name(session: AsyncSession, username: str) -> User:
    return (
        await session.execute(select(User).where(User.org_id == ORG, User.username == username))
    ).scalar_one()


async def count(session: AsyncSession, model: type) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_preview_writes_nothing(session: AsyncSession) -> None:
    result = await run(session, group_snapshot(), apply=False)
    assert result.stats["departments"]["created"] == 8
    assert result.stats["users"]["created"] == 3
    assert not result.applied
    assert await count(session, Department) == 0
    assert await count(session, User) == 0


async def test_initial_sync_builds_tree_users_memberships_titles(session: AsyncSession) -> None:
    result = await run(session, group_snapshot())
    assert result.applied
    assert result.stats["departments"]["created"] == 8
    assert result.stats["users"]["created"] == 3

    weave_vn = await dept_by_ext(session, "11")
    vn = await dept_by_ext(session, "10")
    root = await dept_by_ext(session, "1")
    assert weave_vn.path == f"/{root.id}/{vn.id}/{weave_vn.id}/"
    assert weave_vn.source == "wecom"
    names = await DepartmentRepository(session).path_names(ORG, [weave_vn])
    assert names[weave_vn.id] == "集团 / 越南Flyknit / 织造车间"

    zhang = await user_by_name(session, "zhangsan")
    assert zhang.department_id == weave_vn.id
    assert zhang.source == "wecom" and zhang.job_title == "班组长"
    links = (
        (await session.execute(select(UserDepartment).where(UserDepartment.user_id == zhang.id)))
        .scalars()
        .all()
    )
    assert {(link.department_id, link.is_primary) for link in links} == {
        (weave_vn.id, True),
        ((await dept_by_ext(session, "12")).id, False),
    }
    title = (await session.execute(select(Group).where(Group.name == "职务/班组长"))).scalar_one()
    assert title.source == "wecom"
    assert await session.get(UserGroup, (zhang.id, title.id)) is not None
    assert await count(session, UserIdentity) == 3

    # Second run with identical data is a no-op.
    again = await run(session, group_snapshot())
    assert again.stats["departments"]["created"] == 0
    assert again.stats["departments"]["updated"] == 0
    assert again.stats["users"]["unchanged"] == 3
    assert again.changes["users"] == []


async def test_multi_department_user_gets_both_ancestor_chains(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    await run(session, group_snapshot())
    zhang = await user_by_name(session, "zhangsan")
    principals = await PrincipalResolver(session, authz_cache).resolve(ORG, zhang.id)
    expected = {(await dept_by_ext(session, e)).id for e in ("1", "10", "11", "12")}
    assert principals.dept_ids == expected


async def test_rename_move_archive_and_local_child_path(session: AsyncSession) -> None:
    await run(session, group_snapshot())
    qa = await dept_by_ext(session, "12")
    local_child = Department(
        id=new_id(), org_id=ORG, parent_id=qa.id, name="本地小组", path=f"{qa.path}x/"
    )
    local_child.path = f"{qa.path}{local_child.id}/"
    session.add(local_child)
    await session.commit()

    snap = group_snapshot()
    snap.departments = [d for d in snap.departments if d.external_id not in {"30", "31"}]
    snap.users = [u for u in snap.users if u.external_id != "u3"]
    for d in snap.departments:
        if d.external_id == "12":
            d.parent_external_id = "20"  # 品质部 moves to 总部
        if d.external_id == "21":
            d.name = "法务合规部"
    result = await run(session, snap)
    stats = result.stats["departments"]
    assert stats["moved"] == 1 and stats["archived"] == 2 and stats["updated"] == 2

    hq = await dept_by_ext(session, "20")
    root = await dept_by_ext(session, "1")
    qa = await dept_by_ext(session, "12")
    assert qa.parent_id == hq.id
    assert qa.path == f"/{root.id}/{hq.id}/{qa.id}/"
    await session.refresh(local_child)
    assert local_child.path == f"{qa.path}{local_child.id}/"
    assert (await dept_by_ext(session, "21")).name == "法务合规部"
    assert (await dept_by_ext(session, "31")).status == "archived"
    # u3 left: disabled, not deleted (1 of 3 is below the guard's minimum count).
    assert (await user_by_name(session, "wangwu")).is_active is False
    assert result.stats["users"]["disabled"] == 1

    # Archived department comes back: restored, not duplicated.
    restored = await run(session, group_snapshot())
    assert restored.stats["departments"]["restored"] == 2
    assert restored.stats["users"]["restored"] == 1
    assert (await user_by_name(session, "wangwu")).is_active is True


async def test_disable_guard_aborts_then_force_applies(session: AsyncSession) -> None:
    users = [
        UserRecord(f"u{i}", f"user{i}", f"员工{i}", dept_external_ids=["1"]) for i in range(20)
    ]
    await run(session, Snapshot([DeptRecord("1", "集团")], users))
    shrunk = Snapshot([DeptRecord("1", "集团")], users[:14])  # 6/20 = 30% > 20%

    aborted = await run(session, shrunk)
    assert aborted.aborted and not aborted.applied
    assert "6/20" in (aborted.abort_reason or "")
    active = await session.scalar(select(func.count()).where(User.is_active.is_(True)))
    assert active == 20

    forced = await run(session, shrunk, force=True)
    assert forced.applied
    active = await session.scalar(select(func.count()).where(User.is_active.is_(True)))
    assert active == 14


async def test_adopts_local_department_and_user(session: AsyncSession) -> None:
    root = Department(id=new_id(), org_id=ORG, name="集团", path="")
    root.path = f"/{root.id}/"
    it = Department(id=new_id(), org_id=ORG, parent_id=root.id, name="IT运维", path="")
    it.path = f"{root.path}{it.id}/"
    local = User(org_id=ORG, username="alice", employee_no="E100", department_id=it.id)
    session.add_all([root, it, local])
    await session.commit()

    snap = Snapshot(
        [DeptRecord("1", "集团"), DeptRecord("5", "IT运维", "1")],
        [UserRecord("wx-alice", "wx-alice", "Alice", employee_no="E100", dept_external_ids=["5"])],
    )
    result = await run(session, snap)
    assert result.stats["departments"]["adopted"] == 2
    assert result.stats["departments"]["created"] == 0
    assert result.stats["users"]["adopted"] == 1
    await session.refresh(it)
    await session.refresh(local)
    assert it.source == "wecom" and it.external_id == "5"
    # Username is kept so the existing Keycloak account keeps working.
    assert local.username == "alice" and local.source == "wecom"
    assert result.changes["users"][0]["match"] == "employee_no"
    identity = (await session.execute(select(UserIdentity))).scalar_one()
    assert identity.user_id == local.id and identity.external_id == "wx-alice"


async def test_empty_upstream_fields_keep_local_values(session: AsyncSession) -> None:
    await run(session, group_snapshot())
    snap = group_snapshot()
    snap.users[1].mobile = None
    result = await run(session, snap)
    assert result.stats["users"]["updated"] == 0
    assert (await user_by_name(session, "lisi")).mobile == "13800000000"


async def test_title_change_moves_title_group(session: AsyncSession) -> None:
    await run(session, group_snapshot())
    snap = group_snapshot()
    snap.users[0].title = "车间主任"
    result = await run(session, snap)
    assert result.stats["users"]["updated"] == 1
    zhang = await user_by_name(session, "zhangsan")
    names = (
        (
            await session.execute(
                select(Group.name)
                .join(UserGroup, UserGroup.group_id == Group.id)
                .where(UserGroup.user_id == zhang.id)
            )
        )
        .scalars()
        .all()
    )
    assert list(names) == ["职务/车间主任"]


async def test_secondary_source_only_binds_identities(session: AsyncSession) -> None:
    await run(session, group_snapshot())
    before = await count(session, Department)
    ding = Snapshot(
        [DeptRecord("1", "钉钉根")],
        [
            UserRecord("d1", "d1", "张三", employee_no="VN001", dept_external_ids=["1"]),
            UserRecord("d2", "d2", "李四", mobile="13800000000", dept_external_ids=["1"]),
            UserRecord("d9", "d9", "陌生人", email="nobody@example.com", dept_external_ids=["1"]),
        ],
    )
    result = await run(session, ding, source_type="dingtalk", is_primary=False)
    assert result.stats["identities"] == {"bound": 2, "kept": 0, "removed": 0, "unmatched": 1}
    assert result.changes["unmatched"][0]["name"] == "陌生人"
    assert await count(session, Department) == before
    providers = (
        (
            await session.execute(
                select(UserIdentity.external_id).where(UserIdentity.provider == "dingtalk")
            )
        )
        .scalars()
        .all()
    )
    assert sorted(providers) == ["d1", "d2"]


async def test_archived_department_grants_keep_working(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    await run(session, group_snapshot())
    weave_id = (await dept_by_ext(session, "31")).id
    local = User(org_id=ORG, username="local-member", department_id=weave_id)
    session.add(local)
    await session.commit()
    snap = group_snapshot()
    snap.departments = [d for d in snap.departments if d.external_id != "31"]
    snap.users = [u for u in snap.users if u.external_id != "u3"]
    await run(session, snap)
    assert (await dept_by_ext(session, "31")).status == "archived"
    principals = await PrincipalResolver(session, authz_cache).resolve(ORG, local.id)
    assert weave_id in principals.dept_ids
