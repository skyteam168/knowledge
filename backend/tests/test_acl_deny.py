"""B3: explicit ACL DENY wins over allow / org visibility."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, KbVisibility, KnowledgeBase
from app.services.authz import (
    AclEffect,
    AclPermission,
    AclService,
    AuthzCache,
    PrincipalType,
    ResourceRef,
)
from app.services.knowledge.access import RESOURCE_DOCUMENT, RESOURCE_KB, KnowledgeAccess
from tests.factories import make_group, make_org, make_user
from tests.test_acl_service import as_current

READ = AclPermission.READ
MANAGE = AclPermission.MANAGE


async def _kb(session: AsyncSession, org_id: str, *, visibility: str = "org") -> KnowledgeBase:
    kb = KnowledgeBase(
        org_id=org_id,
        name=f"kb-{visibility}-{org_id[:6]}",
        description=None,
        visibility=visibility,
        watermark=False,
        copy_protect=False,
        download_permission=READ.value,
        created_by=None,
    )
    session.add(kb)
    await session.flush()
    return kb


async def _doc(session: AsyncSession, kb: KnowledgeBase, *, inherit: bool = True) -> Document:
    doc = Document(
        org_id=kb.org_id,
        kb_id=kb.id,
        title="doc",
        filename="doc.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        sha256="a" * 64,
        minio_key="k",
        acl_inherit=inherit,
        tags=[],
        meta={},
    )
    session.add(doc)
    await session.flush()
    return doc


@pytest.mark.acl
async def test_user_deny_wins_over_group_allow(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    member = await make_user(session, org)
    group = await make_group(session, org, member)
    acl = AclService(session)
    doc_ref = ResourceRef(RESOURCE_DOCUMENT, "doc-deny-1")
    await acl.grant(org.id, doc_ref, PrincipalType.GROUP, group.id, READ)
    await acl.grant(
        org.id,
        doc_ref,
        PrincipalType.USER,
        member.id,
        READ,
        effect=AclEffect.DENY,
    )
    user = await as_current(session, authz_cache, member)
    assert await acl.effective_permission(user.principals, doc_ref) is None
    assert not await acl.can(user, doc_ref, READ)


@pytest.mark.acl
async def test_document_deny_under_org_visible_inherit(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    alice = await make_user(session, org)
    bob = await make_user(session, org)
    kb = await _kb(session, org.id, visibility=KbVisibility.ORG.value)
    access = KnowledgeAccess(session)
    await access.replace_entries(
        org.id,
        RESOURCE_KB,
        kb.id,
        [("user", alice.id, MANAGE.value, "allow")],
        alice.id,
    )
    doc = await _doc(session, kb, inherit=True)
    await access.replace_entries(
        org.id,
        RESOURCE_DOCUMENT,
        doc.id,
        [("user", bob.id, READ.value, "deny")],
        alice.id,
    )
    await session.flush()

    bob_user = await as_current(session, authz_cache, bob)
    alice_user = await as_current(session, authz_cache, alice)

    assert await access.kb_permission(bob_user, kb) == READ
    assert await access.document_permission(bob_user, doc, kb) is None
    # Manager still sees the document to repair ACL.
    assert await access.document_permission(alice_user, doc, kb) == MANAGE


@pytest.mark.acl
async def test_kb_deny_blocks_org_visibility(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    user = await make_user(session, org)
    kb = await _kb(session, org.id, visibility=KbVisibility.ORG.value)
    access = KnowledgeAccess(session)
    await access.replace_entries(
        org.id,
        RESOURCE_KB,
        kb.id,
        [("user", user.id, READ.value, "deny")],
        None,
    )
    current = await as_current(session, authz_cache, user)
    assert await access.kb_permission(current, kb) is None
