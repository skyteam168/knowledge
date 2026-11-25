"""Industrial object state machines (Wave A Task4). Device status is the pilot."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.ontology.attributes import DEVICE_STATUS_ENUM_MAP, resolve_enum_raw


class DeviceState(StrEnum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    MAINTENANCE = "MAINTENANCE"
    IDLE = "IDLE"
    UNKNOWN = "UNKNOWN"


# Default allowed transitions. MAINTENANCE from RUNNING requires explicit permit.
_DEVICE_TRANSITIONS: dict[DeviceState, frozenset[DeviceState]] = {
    DeviceState.RUNNING: frozenset(
        {DeviceState.STOPPED, DeviceState.IDLE, DeviceState.UNKNOWN}
    ),
    DeviceState.STOPPED: frozenset(
        {
            DeviceState.RUNNING,
            DeviceState.MAINTENANCE,
            DeviceState.IDLE,
            DeviceState.UNKNOWN,
        }
    ),
    DeviceState.MAINTENANCE: frozenset(
        {DeviceState.STOPPED, DeviceState.IDLE, DeviceState.RUNNING, DeviceState.UNKNOWN}
    ),
    DeviceState.IDLE: frozenset(
        {
            DeviceState.RUNNING,
            DeviceState.STOPPED,
            DeviceState.MAINTENANCE,
            DeviceState.UNKNOWN,
        }
    ),
    DeviceState.UNKNOWN: frozenset(set(DeviceState) - {DeviceState.UNKNOWN}),
}


@dataclass(frozen=True, slots=True)
class NormalizedDeviceStatus:
    standard_status: DeviceState
    status_label: str
    raw: str | None


def normalize_device_status(raw: Any) -> NormalizedDeviceStatus:
    """Map MES-style 0/1/2/… or already-standard codes to DeviceState + label."""
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return NormalizedDeviceStatus(DeviceState.UNKNOWN, "未知", None)
    text = str(raw).strip()
    resolved = resolve_enum_raw(text, DEVICE_STATUS_ENUM_MAP)
    if resolved is not None:
        try:
            state = DeviceState(resolved.standard)
        except ValueError:
            state = DeviceState.UNKNOWN
        return NormalizedDeviceStatus(state, resolved.label, text)
    upper = text.upper()
    try:
        state = DeviceState(upper)
        # Prefer Chinese label from map when standard matches
        for entry in DEVICE_STATUS_ENUM_MAP.values():
            if entry.standard == state.value:
                return NormalizedDeviceStatus(state, entry.label, text)
        return NormalizedDeviceStatus(state, state.value, text)
    except ValueError:
        return NormalizedDeviceStatus(DeviceState.UNKNOWN, "未知", text)


def can_transition(
    from_state: DeviceState | str,
    to_state: DeviceState | str,
    *,
    permit: bool = False,
    raise_on_illegal: bool = False,
) -> bool:
    """Return whether Device may move from→to.

    ``RUNNING → MAINTENANCE`` is blocked unless ``permit=True`` (write-path reserved).
    """
    src = DeviceState(str(from_state))
    dst = DeviceState(str(to_state))
    if src == dst:
        return True
    allowed = set(_DEVICE_TRANSITIONS.get(src, frozenset()))
    if dst == DeviceState.MAINTENANCE and src == DeviceState.RUNNING:
        ok = permit
    else:
        ok = dst in allowed
    if not ok and raise_on_illegal:
        raise ValueError(f"illegal device transition {src.value}→{dst.value}")
    return ok
