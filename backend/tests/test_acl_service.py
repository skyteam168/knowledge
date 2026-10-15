from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization, User
from app.services.authz import (
    AclPermission,
    AclService,
    AuthzCache,
    CurrentUser,
    PrincipalResolver,
    Principals,
    PrincipalType,
    ResourceRef,
)
from tests.factories import make_dept, make_group, make_org, make_role, make_user

DOC = ResourceRef("document", "doc-1")
READ, EDIT, MANAGE = AclPermission.READ, AclPermission.EDIT, AclPermission.MANAGE


async def as_current(
    session: AsyncSession, cache: AuthzCache, user: User, perms: frozenset[str] = frozenset()
) -> CurrentUser:
    principals = await PrincipalResolver(session, cache).resolve(user.org_id, user.id)
    return CurrentUser(
        id=user.id,
        org_id=user.org_id,
        username=user.username,
        display_name=None,
        principals=principals,
        permissions=perms,
    )


@pytest.fixture
async def org(session: AsyncSession) -> Organization:
    return await make_org(session)


async def test_no_acl_means_no_access(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    user = await as_current(session, authz_cache, await make_user(session, org))
    acl = AclService(session)
    for perm in AclPermission:
        assert not await acl.can(user, DOC, perm)
    assert await acl.effective_permission(user.principals, DOC) is None


async def test_direct_user_grant_and_permission_hierarchy(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    db_user = await make_user(session, org)
    acl = AclService(session)
    await acl.grant(org.id, DOC, PrincipalType.USER, db_user.id, READ)
    user = await as_current(session, authz_cache, db_user)
    assert await acl.can(user, DOC, READ)
    assert not await acl.can(user, DOC, EDIT)

    await acl.grant(org.id, DOC, PrincipalType.USER, db_user.id, MANAGE)
    assert await acl.can(user, DOC, EDIT), "manage implies edit"
    assert await acl.can(user, DOC, MANAGE)
    assert await acl.effective_permission(user.principals, DOC) == MANAGE


async def test_group_grant(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    member, outsider = await make_user(session, org), await make_user(session, org)
    group = await make_group(session, org, member)
    acl = AclService(session)
    await acl.grant(org.id, DOC, PrincipalType.GROUP, group.id, EDIT)

    m = await as_current(session, authz_cache, member)
    assert await acl.can(m, DOC, READ) and await acl.can(m, DOC, EDIT)
    assert not await acl.can(m, DOC, MANAGE)
    assert not await acl.can(await as_current(session, authz_cache, outsider), DOC, READ)


async def test_role_grant(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    holder, other = await make_user(session, org), await make_user(session, org)
    role = await make_role(session, org, holder)
    acl = AclService(session)
    await acl.grant(org.id, DOC, PrincipalType.ROLE, role.id, MANAGE)

    assert await acl.can(await as_current(session, authz_cache, holder), DOC, MANAGE)
    assert not await acl.can(await as_current(session, authz_cache, other), DOC, READ)


async def test_department_grant_is_inherited_by_sub_departments(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    root = await make_dept(session, org)
    rd = await make_dept(session, org, root)
    rd_backend = await make_dept(session, org, rd)
    sales = await make_dept(session, org, root)
    acl = AclService(session)
    await acl.grant(org.id, DOC, PrincipalType.DEPT, rd.id, READ)

    deep = await as_current(session, authz_cache, await make_user(session, org, rd_backend))
    direct = await as_current(session, authz_cache, await make_user(session, org, rd))
    sibling = await as_current(session, authz_cache, await make_user(session, org, sales))
    parent = await as_current(session, authz_cache, await make_user(session, org, root))

    assert await acl.can(deep, DOC, READ), "grant on parent dept applies to descendants"
    assert await acl.can(direct, DOC, READ)
    assert not await acl.can(sibling, DOC, READ)
    assert not await acl.can(parent, DOC, READ), "grant does not flow upwards"


async def test_org_wide_grant(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    acl = AclService(session)
    await acl.grant(org.id, DOC, PrincipalType.ORG, org.id, READ)
    user = await as_current(session, authz_cache, await make_user(session, org))
    assert await acl.can(user, DOC, READ)
    assert not await acl.can(user, DOC, EDIT)


async def test_highest_permission_across_principals_wins(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    dept = await make_dept(session, org)
    db_user = await make_user(session, org, dept)
    group = await make_group(session, org, db_user)
    acl = AclService(session)
    await acl.grant(org.id, DOC, PrincipalType.DEPT, dept.id, READ)
    await acl.grant(org.id, DOC, PrincipalType.GROUP, group.id, EDIT)
    user = await as_current(session, authz_cache, db_user)
    assert await acl.effective_permission(user.principals, DOC) == EDIT


async def test_acl_is_scoped_to_resource_and_org(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    other_org = await make_org(session, "other")
    db_user = await make_user(session, org)
    acl = AclService(session)
    # Same principal id string, but row belongs to another tenant.
    await acl.grant(other_org.id, DOC, PrincipalType.USER, db_user.id, MANAGE)
    await acl.grant(org.id, ResourceRef("document", "doc-2"), PrincipalType.USER, db_user.id, READ)
    await acl.grant(org.id, ResourceRef("kb", DOC.id), PrincipalType.USER, db_user.id, READ)

    user = await as_current(session, authz_cache, db_user)
    assert not await acl.can(user, DOC, READ)


async def test_superuser_bypasses_acl(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    user = await as_current(session, authz_cache, await make_user(session, org), frozenset({"*"}))
    assert await AclService(session).can(user, DOC, MANAGE)


async def test_grant_is_idempotent_and_revoke(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    db_user = await make_user(session, org)
    acl = AclService(session)
    first = await acl.grant(org.id, DOC, PrincipalType.USER, db_user.id, READ)
    second = await acl.grant(org.id, DOC, PrincipalType.USER, db_user.id, READ)
    assert first.id == second.id
    assert len(await acl.list_entries(org.id, DOC)) == 1

    assert await acl.revoke(org.id, DOC, PrincipalType.USER, db_user.id) == 1
    user = await as_current(session, authz_cache, db_user)
    assert not await acl.can(user, DOC, READ)


def _principals() -> Principals:
    return Principals(
        org_id="o1",
        user_id="u1",
        group_ids=frozenset({"g2", "g1"}),
        role_ids=frozenset({"r1"}),
        dept_ids=frozenset({"d1", "d0"}),
    )


TOKENS = ["user:u1", "org:o1", "group:g1", "group:g2", "role:r1", "dept:d0", "dept:d1"]


def test_build_filter_qdrant() -> None:
    f = AclService.build_filter(_principals())
    assert f.to_qdrant() == {
        "must": [
            {"key": "org_id", "match": {"value": "o1"}},
            {"key": "acl_read_principals", "match": {"any": TOKENS}},
        ]
    }


def test_build_filter_opensearch() -> None:
    f = AclService.build_filter(_principals())
    assert f.to_opensearch() == {
        "bool": {
            "filter": [
                {"term": {"org_id": "o1"}},
                {"terms": {"acl_read_principals": TOKENS}},
            ]
        }
    }


def test_build_filter_restricts_knowledge_bases() -> None:
    f = AclService.build_filter(_principals(), kb_ids=["kb2", "kb1", "kb2"])
    assert f.to_qdrant()["must"][1] == {"key": "kb_id", "match": {"any": ["kb1", "kb2"]}}
    assert f.to_opensearch()["bool"]["filter"][1] == {"terms": {"kb_id": ["kb1", "kb2"]}}


def test_build_filter_minimal_principals_still_match_org_wide_documents() -> None:
    f = AclService.build_filter(Principals(org_id="o1", user_id="u1"))
    assert f.to_qdrant()["must"][1]["match"]["any"] == ["user:u1", "org:o1"]


def test_build_filter_bypass_keeps_tenant_isolation() -> None:
    f = AclService.build_filter(_principals(), bypass_acl=True)
    assert f.to_qdrant() == {"must": [{"key": "org_id", "match": {"value": "o1"}}]}
    assert f.to_opensearch() == {"bool": {"filter": [{"term": {"org_id": "o1"}}]}}


def _qdrant_match(payload: dict[str, Any], flt: dict[str, Any]) -> bool:
    """Evaluates the subset of Qdrant filter syntax produced by AclFilter."""
    for cond in flt["must"]:
        value = payload.get(cond["key"])
        values = value if isinstance(value, list) else [value]
        match = cond["match"]
        wanted = match["any"] if "any" in match else [match["value"]]
        if not set(values) & set(wanted):
            return False
    return True


async def test_filter_matches_materialized_document_principals(
    session: AsyncSession, authz_cache: AuthzCache, org: Organization
) -> None:
    """End to end: principals written by the indexer vs. the filter built for a reader."""
    from app.models import Document, KnowledgeBase
    from app.services.indexing.principals import compute_read_principals

    root = await make_dept(session, org)
    child = await make_dept(session, org, root)
    reader = await make_user(session, org, child)
    outsider = await make_user(session, org)
    group = await make_group(session, org, reader)

    kb = KnowledgeBase(org_id=org.id, name="kb", visibility="restricted")
    session.add(kb)
    await session.flush()
    acl = AclService(session)
    await acl.grant(org.id, ResourceRef("kb", kb.id), PrincipalType.DEPT, root.id, READ)

    def doc(inherit: bool) -> Document:
        return Document(
            org_id=org.id,
            kb_id=kb.id,
            title="t",
            filename=f"{inherit}.txt",
            mime_type="text/plain",
            size_bytes=1,
            sha256="0" * 64,
            minio_key="k",
            acl_inherit=inherit,
            tags=[],
            meta={},
        )

    inherited, own = doc(True), doc(False)
    session.add_all([inherited, own])
    await session.flush()
    await acl.grant(org.id, ResourceRef("document", own.id), PrincipalType.GROUP, group.id, READ)

    principals = await compute_read_principals(session, [inherited, own])
    assert principals[inherited.id] == [f"dept:{root.id}"]
    assert principals[own.id] == [f"group:{group.id}"]

    reader_filter = AclService.build_filter(
        (await as_current(session, authz_cache, reader)).principals
    ).to_qdrant()
    outsider_filter = AclService.build_filter(
        (await as_current(session, authz_cache, outsider)).principals
    ).to_qdrant()
    for doc_id, tokens in principals.items():
        payload = {"org_id": org.id, "acl_read_principals": tokens}
        assert _qdrant_match(payload, reader_filter), doc_id
        assert not _qdrant_match(payload, outsider_filter), doc_id
    assert not _qdrant_match(
        {"org_id": "another-org", "acl_read_principals": principals[own.id]}, reader_filter
    )
