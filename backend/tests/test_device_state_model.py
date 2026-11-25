"""Wave A Task4: Device status state machine + normalization."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.models.base import new_id
from app.ontology.state_machines import (
    DeviceState,
    can_transition,
    normalize_device_status,
)
from app.models import EquipDevice, StructuredSource, StructuredSourceType
from app.schemas.open_api import OpenGetObjectIn
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.open_api.auth import ApiCaller
from app.services.open_api.ontology_tools import OpenOntologyTools


def test_raw_codes_map_to_standard_states() -> None:
    assert normalize_device_status(0).standard_status == DeviceState.RUNNING
    assert normalize_device_status("1").standard_status == DeviceState.STOPPED
    assert normalize_device_status("2").status_label == "保养"
    assert normalize_device_status("unknown-x").standard_status == DeviceState.UNKNOWN


def test_illegal_transition_running_to_maintenance_without_permit() -> None:
    assert can_transition(DeviceState.RUNNING, DeviceState.STOPPED) is True
    assert (
        can_transition(DeviceState.RUNNING, DeviceState.MAINTENANCE, permit=False)
        is False
    )
    assert (
        can_transition(DeviceState.RUNNING, DeviceState.MAINTENANCE, permit=True)
        is True
    )
    with pytest.raises(ValueError, match="illegal"):
        can_transition(
            DeviceState.RUNNING,
            DeviceState.MAINTENANCE,
            permit=False,
            raise_on_illegal=True,
        )


async def test_get_object_exposes_standard_device_status(
    session: AsyncSession,
) -> None:
    org_id = "org-device-state"
    uid = new_id()
    user = CurrentUser(
        id=uid,
        org_id=org_id,
        username="state",
        display_name="State",
        principals=Principals(org_id, uid),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    ctx = RequestContext(
        user, AuditContext(org_id=org_id, actor_id=uid, actor_name="State")
    )
    source = StructuredSource(
        org_id=org_id,
        name="state-src",
        type=StructuredSourceType.MES.value,
        enabled=True,
        meta={},
    )
    session.add(source)
    await session.flush()
    device = EquipDevice(
        org_id=org_id,
        source_id=source.id,
        external_id="EQ-STATE-1",
        name="状态测设备",
        status="0",
        location="A",
        meta={},
    )
    session.add(device)
    await session.flush()
    caller = ApiCaller(
        client_id=new_id(),
        key_id=new_id(),
        org_id=org_id,
        name="state-agent",
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
        OpenGetObjectIn(object_type="device", object_id=device.id)
    )
    assert got.status == "0"
    assert got.standard_status == "RUNNING"
    assert got.status_label == "运行"
