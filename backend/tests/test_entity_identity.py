"""Wave A Task2: Canonical Entity + multi-system identifier mapping."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.models.base import new_id
from app.schemas.open_api import OpenGetObjectIn
from app.schemas.structured import StructuredRecordCreate, StructuredSourceCreate
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.open_api.auth import ApiCaller
from app.services.open_api.ontology_tools import OpenOntologyTools
from app.services.structured.identity import EntityIdentityService
from app.services.structured.service import StructuredService


ORG_GET = "org-id-get-object"


@pytest.fixture
def identity(session: AsyncSession) -> EntityIdentityService:
    return EntityIdentityService(session)


async def test_resolve_maps_mes_and_qr_to_same_canonical(
    identity: EntityIdentityService,
) -> None:
    org_id = "org-id-mes-qr"
    entity = await identity.create_canonical(
        org_id, object_type="device", display_name="电脑编织横机"
    )
    await identity.attach_identifier(
        entity.id,
        org_id=org_id,
        system="mes",
        id_kind="asset_code",
        external_id="F0305",
        is_primary=True,
    )
    await identity.attach_identifier(
        entity.id,
        org_id=org_id,
        system="qr",
        id_kind="qr_code",
        external_id="QR-0091",
    )

    from_mes = await identity.resolve_identifier(
        org_id, system="mes", external_id="F0305"
    )
    from_qr = await identity.resolve_identifier(
        org_id, system="qr", external_id="QR-0091"
    )
    assert from_mes is not None and from_qr is not None
    assert from_mes.id == from_qr.id == entity.id
    assert from_mes.status == "active"


async def test_conflict_when_same_code_different_systems_flagged(
    identity: EntityIdentityService,
) -> None:
    """Same asset code under MES vs EAM mapping to two entities → conflict, no silent merge."""
    org_id = "org-id-conflict"
    mes_entity = await identity.create_canonical(
        org_id, object_type="device", display_name="MES侧机台"
    )
    eam_entity = await identity.create_canonical(
        org_id, object_type="device", display_name="EAM侧机台"
    )
    await identity.attach_identifier(
        mes_entity.id,
        org_id=org_id,
        system="mes",
        id_kind="asset_code",
        external_id="F0305",
        is_primary=True,
    )
    await identity.attach_identifier(
        eam_entity.id,
        org_id=org_id,
        system="eam",
        id_kind="asset_code",
        external_id="F0305",
        is_primary=True,
    )

    result = await identity.resolve_match(
        org_id,
        [
            {"system": "mes", "external_id": "F0305"},
            {"system": "eam", "external_id": "F0305"},
        ],
    )
    assert result.status == "conflict"
    assert set(result.canonical_ids) == {mes_entity.id, eam_entity.id}
    # entities stay distinct; no auto-merge
    still_mes = await identity.resolve_identifier(
        org_id, system="mes", external_id="F0305"
    )
    still_eam = await identity.resolve_identifier(
        org_id, system="eam", external_id="F0305"
    )
    assert still_mes is not None and still_eam is not None
    assert still_mes.id != still_eam.id


async def test_rebinding_identifier_to_other_canonical_rejected(
    identity: EntityIdentityService,
) -> None:
    org_id = "org-id-rebind"
    a = await identity.create_canonical(org_id, "device", "A")
    b = await identity.create_canonical(org_id, "device", "B")
    await identity.attach_identifier(
        a.id,
        org_id=org_id,
        system="mes",
        id_kind="asset_code",
        external_id="X1",
        is_primary=True,
    )
    with pytest.raises(Exception) as exc:
        await identity.attach_identifier(
            b.id,
            org_id=org_id,
            system="mes",
            id_kind="asset_code",
            external_id="X1",
        )
    assert "conflict" in str(exc.value).lower() or getattr(
        exc.value, "code", ""
    ) in {"conflict", "CONFLICT"}


async def test_get_object_exposes_canonical_id_and_identifiers(
    session: AsyncSession,
    identity: EntityIdentityService,
) -> None:
    user_id = new_id()
    user = CurrentUser(
        id=user_id,
        org_id=ORG_GET,
        username="id-tester",
        display_name="Id Tester",
        principals=Principals(ORG_GET, user_id),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    ctx = RequestContext(
        user,
        AuditContext(org_id=ORG_GET, actor_id=user.id, actor_name=user.display_name),
    )
    structured = StructuredService(
        session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60)
    )
    domains = await structured.list_domains()
    equipment = next(d for d in domains if d.code == "equipment")
    source = await structured.create_source(
        StructuredSourceCreate(name="id-src", type="mes")
    )
    equip = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="equipment",
            external_id="EQ-ID-1",
            title="身份测设备",
            attrs={"model": "M"},
        )
    )
    canonical = await identity.ensure_for_structured(
        ORG_GET,
        object_type="equipment",
        display_name=equip.title,
        structured_object_id=equip.id,
        system="mes",
        external_id="EQ-ID-1",
        id_kind="asset_code",
    )
    await identity.attach_identifier(
        canonical.id,
        org_id=ORG_GET,
        system="qr",
        id_kind="qr_code",
        external_id="QR-ID-1",
    )
    await session.flush()

    caller = ApiCaller(
        client_id=new_id(),
        key_id=new_id(),
        org_id=ORG_GET,
        name="id-agent",
        kb_ids=frozenset({new_id()}),
        scopes=frozenset({"entity", "mcp"}),
        rate_limit_per_minute=60,
        daily_quota=0,
        user=user,
    )
    tools = OpenOntologyTools(
        session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60), caller
    )
    got = await tools.get_object(
        OpenGetObjectIn(object_type="equipment", external_id="EQ-ID-1")
    )
    assert got.canonical_id == canonical.id
    systems = {i.system: i.external_id for i in got.identifiers}
    assert systems["mes"] == "EQ-ID-1"
    assert systems["qr"] == "QR-ID-1"
