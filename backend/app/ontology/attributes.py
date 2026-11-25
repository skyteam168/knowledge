"""Typed attribute schemas for structured / industrial objects (O1.2).

Single source of truth for:
- Python validation (API create)
- JSON Schema export (docs / OpenAPI-adjacent)
- Human-readable docs

Policy (strict for types that declare a schema):
- Missing required attr → reject
- Quantity missing unit / wrong type → reject
- Number outside min/max → reject
- Unknown keys → reject (keeps critical fields out of free-form meta)
- Object types with no schema (custom like ``recipe``) → attrs unrestricted
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Mapping

from app.models.structured import StructuredObjectType

AttrKind = Literal[
    "string",
    "number",
    "integer",
    "boolean",
    "quantity",
    "enum",
    "string_list",
]


@dataclass(frozen=True, slots=True)
class EnumMapEntry:
    """raw source value → standardized code + display label (+ optional i18n)."""

    standard: str
    label: str
    labels: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class ResolvedEnum:
    standard: str
    label: str
    raw: str


@dataclass(frozen=True, slots=True)
class AttrDef:
    name: str
    kind: AttrKind
    required: bool = False
    description: str = ""
    unit: str | None = None
    allowed_units: frozenset[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    enum_values: frozenset[str] | None = None
    enum_map: Mapping[str, EnumMapEntry] | None = None
    labels: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class ObjectTypeSchema:
    object_type: str
    label: str
    description: str
    attributes: tuple[AttrDef, ...]

    def attr_map(self) -> dict[str, AttrDef]:
        return {a.name: a for a in self.attributes}


@dataclass(frozen=True, slots=True)
class AttrIssue:
    code: str
    path: str
    message: str


def _q(
    name: str,
    *,
    required: bool = False,
    unit: str,
    allowed_units: frozenset[str] | None | Literal["any"] = None,
    minimum: float | None = None,
    maximum: float | None = None,
    description: str = "",
) -> AttrDef:
    # None → default to the declared unit only; "any" → unit required but unrestricted.
    if allowed_units == "any":
        units: frozenset[str] | None = None
    elif allowed_units is None:
        units = frozenset({unit})
    else:
        units = allowed_units
    return AttrDef(
        name=name,
        kind="quantity",
        required=required,
        unit=unit,
        allowed_units=units,
        minimum=minimum,
        maximum=maximum,
        description=description,
    )


def _s(
    name: str,
    *,
    required: bool = False,
    description: str = "",
) -> AttrDef:
    return AttrDef(name=name, kind="string", required=required, description=description)


def _e(
    name: str,
    values: frozenset[str],
    *,
    required: bool = False,
    description: str = "",
) -> AttrDef:
    return AttrDef(
        name=name,
        kind="enum",
        required=required,
        enum_values=values,
        description=description,
    )


def _n(
    name: str,
    *,
    required: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
    description: str = "",
) -> AttrDef:
    return AttrDef(
        name=name,
        kind="number",
        required=required,
        minimum=minimum,
        maximum=maximum,
        description=description,
    )


def _i(
    name: str,
    *,
    required: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
    description: str = "",
) -> AttrDef:
    return AttrDef(
        name=name,
        kind="integer",
        required=required,
        minimum=minimum,
        maximum=maximum,
        description=description,
    )


_SCHEMAS: dict[str, ObjectTypeSchema] = {
    StructuredObjectType.SITE.value: ObjectTypeSchema(
        object_type="site",
        label="Site",
        description="ISA-95 Site / 工厂或厂区",
        attributes=(
            _s("code", required=True, description="厂区编码"),
            _s("timezone", description="IANA 时区，如 Asia/Ho_Chi_Minh"),
            _s("country", description="国家/地区代码"),
        ),
    ),
    StructuredObjectType.AREA.value: ObjectTypeSchema(
        object_type="area",
        label="Area",
        description="ISA-95 Area / 车间或区域",
        attributes=(
            _s("code", required=True, description="区域编码"),
            _s("site_external_id", required=True, description="所属工厂外部编号"),
        ),
    ),
    StructuredObjectType.LINE.value: ObjectTypeSchema(
        object_type="line",
        label="Line",
        description="ISA-95 Production Line / 产线",
        attributes=(
            _s("code", required=True, description="产线编码"),
            _s("area_external_id", required=True, description="所属车间外部编号"),
            _s("site_external_id", description="所属工厂外部编号（可选冗余）"),
        ),
    ),
    StructuredObjectType.EQUIPMENT.value: ObjectTypeSchema(
        object_type="equipment",
        label="Equipment",
        description="ISA-95 Equipment（层级设备；与 equip_devices 的 device 并存）",
        attributes=(
            _s("model", description="型号"),
            _s("manufacturer", description="制造商"),
            _s("line_external_id", description="所属产线外部编号"),
            _s("area_external_id", description="所属车间外部编号"),
            _q(
                "rated_power",
                unit="kW",
                allowed_units=frozenset({"kW", "W"}),
                minimum=0,
                description="额定功率",
            ),
        ),
    ),
    StructuredObjectType.COMPONENT.value: ObjectTypeSchema(
        object_type="component",
        label="Component",
        description="设备部件",
        attributes=(
            _s(
                "equipment_external_id",
                required=True,
                description="所属设备外部编号（equipment 或 device）",
            ),
            _s("part_number", description="件号"),
            _s("position", description="安装位置"),
        ),
    ),
    StructuredObjectType.MATERIAL.value: ObjectTypeSchema(
        object_type="material",
        label="Material",
        description="物料",
        attributes=(
            _s("sku", required=True, description="料号"),
            _s("spec", description="规格说明"),
            _q(
                "unit_weight",
                unit="kg",
                allowed_units=frozenset({"kg", "g"}),
                minimum=0,
                description="单件重量",
            ),
        ),
    ),
    StructuredObjectType.OPERATION.value: ObjectTypeSchema(
        object_type="operation",
        label="Operation",
        description="工序",
        attributes=(
            _s("line_external_id", description="所属产线"),
            _i("sequence", required=True, minimum=1, description="工序序号"),
            _s("work_center", description="工作中心"),
        ),
    ),
    StructuredObjectType.PROCESS_PARAMETER.value: ObjectTypeSchema(
        object_type="process_parameter",
        label="Process parameter",
        description="工艺参数与规格限",
        attributes=(
            _s("operation_external_id", description="所属工序外部编号"),
            _s("name", required=True, description="参数名"),
            _q(
                "setpoint",
                required=True,
                unit="1",
                allowed_units="any",
                description="设定值（必须带 unit）",
            ),
            _q(
                "lower_limit",
                unit="1",
                allowed_units="any",
                description="下限",
            ),
            _q(
                "upper_limit",
                unit="1",
                allowed_units="any",
                description="上限",
            ),
        ),
    ),
    StructuredObjectType.FAILURE_MODE.value: ObjectTypeSchema(
        object_type="failure_mode",
        label="Failure mode",
        description="FMEA 故障模式",
        attributes=(
            _s(
                "equipment_external_id",
                required=True,
                description="关联设备外部编号",
            ),
            _s("code", required=True, description="故障模式编码"),
            _s("component_external_id", description="关联部件外部编号"),
            _i("severity", minimum=1, maximum=10, description="严重度 1–10"),
            _i("occurrence", minimum=1, maximum=10, description="发生度 1–10"),
            _i("detection", minimum=1, maximum=10, description="探测度 1–10"),
        ),
    ),
    StructuredObjectType.EVENT.value: ObjectTypeSchema(
        object_type="event",
        label="Event",
        description="报警 / 停机等事件",
        attributes=(
            _s("equipment_external_id", required=True, description="关联设备"),
            _e(
                "event_type",
                frozenset({"alarm", "downtime", "quality", "other"}),
                required=True,
                description="事件类型",
            ),
            _s("occurred_at", required=True, description="发生时间 ISO-8601"),
            _s("ended_at", description="结束时间 ISO-8601（停机等）"),
            _e(
                "severity",
                frozenset({"low", "medium", "high", "critical"}),
                description="严重级别",
            ),
            _s("message", description="事件摘要"),
        ),
    ),
    # Dedicated equip_* rows: typed extras in meta (columns stay authoritative).
    StructuredObjectType.DEVICE.value: ObjectTypeSchema(
        object_type="device",
        label="Device",
        description="equip_devices.meta 扩展字段（name/status/location 在列上）",
        attributes=(
            _s("model", description="型号"),
            _s("manufacturer", description="制造商"),
            _q(
                "rated_power",
                unit="kW",
                allowed_units=frozenset({"kW", "W"}),
                minimum=0,
                description="额定功率",
            ),
        ),
    ),
    StructuredObjectType.WORK_ORDER.value: ObjectTypeSchema(
        object_type="work_order",
        label="Work order",
        description="equip_work_orders.meta 扩展字段",
        attributes=(
            _e(
                "priority",
                frozenset({"low", "normal", "high", "urgent"}),
                description="优先级",
            ),
            _s("failure_mode_code", description="关联故障模式编码"),
        ),
    ),
    StructuredObjectType.SPARE_PART.value: ObjectTypeSchema(
        object_type="spare_part",
        label="Spare part",
        description="equip_spare_parts.meta 扩展字段",
        attributes=(
            _n("min_qty", minimum=0, description="安全库存"),
            _s("compatible_equipment_external_id", description="适用设备外部编号"),
        ),
    ),
}

# Shared MES-style device status raw→standard map (column or meta).
DEVICE_STATUS_ENUM_MAP: dict[str, EnumMapEntry] = {
    "0": EnumMapEntry(
        "RUNNING",
        "运行",
        {"zh": "运行", "en": "Running", "vi": "Đang chạy"},
    ),
    "1": EnumMapEntry(
        "STOPPED",
        "停机",
        {"zh": "停机", "en": "Stopped", "vi": "Dừng"},
    ),
    "2": EnumMapEntry(
        "MAINTENANCE",
        "保养",
        {"zh": "保养", "en": "Maintenance", "vi": "Bảo trì"},
    ),
    "3": EnumMapEntry(
        "IDLE",
        "空闲",
        {"zh": "空闲", "en": "Idle", "vi": "Nhàn"},
    ),
}


def schema_for(object_type: str) -> ObjectTypeSchema | None:
    return _SCHEMAS.get(object_type.strip().lower())


def list_schemas() -> list[ObjectTypeSchema]:
    return sorted(_SCHEMAS.values(), key=lambda s: s.object_type)


def _coerce_enum_map(
    enum_map: Mapping[str, EnumMapEntry | Mapping[str, Any]] | None,
) -> dict[str, EnumMapEntry]:
    if not enum_map:
        return {}
    out: dict[str, EnumMapEntry] = {}
    for raw, entry in enum_map.items():
        key = str(raw).strip()
        if isinstance(entry, EnumMapEntry):
            out[key] = entry
            continue
        if isinstance(entry, Mapping):
            standard = str(entry.get("standard") or "").strip()
            label = str(entry.get("label") or standard).strip()
            if not standard:
                continue
            labels_raw = entry.get("labels")
            labels = (
                {str(k): str(v) for k, v in labels_raw.items()}
                if isinstance(labels_raw, Mapping)
                else None
            )
            out[key] = EnumMapEntry(standard=standard, label=label, labels=labels)
    return out


def resolve_enum_raw(
    raw: Any,
    enum_map: Mapping[str, EnumMapEntry | Mapping[str, Any]] | None,
) -> ResolvedEnum | None:
    """Map a raw or already-standard value via enum_map; None if unknown."""
    coerced = _coerce_enum_map(enum_map)
    if not coerced or raw is None:
        return None
    key = str(raw).strip()
    if not key:
        return None
    if key in coerced:
        entry = coerced[key]
        return ResolvedEnum(standard=entry.standard, label=entry.label, raw=key)
    for raw_key, entry in coerced.items():
        if entry.standard == key:
            return ResolvedEnum(standard=entry.standard, label=entry.label, raw=raw_key)
    return None


def validate_enum_raw(
    raw: Any,
    enum_map: Mapping[str, EnumMapEntry | Mapping[str, Any]] | None,
    *,
    path: str = "status",
) -> list[AttrIssue]:
    """Reject unknown raw status values against an enum_map (registered types)."""
    coerced = _coerce_enum_map(enum_map)
    if not coerced:
        return []
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return [AttrIssue("required", path, f"{path} 缺少枚举值")]
    if resolve_enum_raw(raw, coerced) is None:
        allowed = ", ".join(sorted(coerced.keys()))
        return [
            AttrIssue(
                "enum_unknown",
                path,
                f"{path}={raw!r} 不在枚举映射 [{allowed}] 中",
            )
        ]
    return []


def parse_iso_datetime(raw: Any) -> datetime | None:
    """Parse ISO-8601 timestamp; return None if missing/blank; raise ValueError if bad."""
    from datetime import UTC

    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def event_timeline_fields(
    attrs: dict[str, Any] | None,
) -> tuple[datetime | None, datetime | None, str | None]:
    """Denorm columns for event rows: occurred_at, ended_at, event_type."""
    data = attrs or {}
    occurred = parse_iso_datetime(data.get("occurred_at"))
    ended = parse_iso_datetime(data.get("ended_at"))
    et = data.get("event_type")
    event_type = str(et).strip().lower() if et is not None and str(et).strip() else None
    return occurred, ended, event_type


def validate_attrs(
    object_type: str,
    attrs: dict[str, Any] | None,
    *,
    strict_unknown: bool = True,
) -> list[AttrIssue]:
    """Validate attrs/meta against the object-type schema.

    Types without a registered schema return no issues (custom object types).
    """
    schema = schema_for(object_type)
    if schema is None:
        return []
    data = dict(attrs or {})
    issues: list[AttrIssue] = []
    known = schema.attr_map()

    if strict_unknown:
        for key in sorted(data):
            if key not in known:
                issues.append(
                    AttrIssue(
                        "unknown_attr",
                        key,
                        f"属性 {key} 不在 {schema.object_type} 的 schema 中",
                    )
                )

    for attr in schema.attributes:
        raw = data.get(attr.name, None)
        if raw is None or raw == "":
            if attr.required:
                issues.append(
                    AttrIssue(
                        "required",
                        attr.name,
                        f"缺少必填属性 {attr.name}",
                    )
                )
            continue
        issues.extend(_validate_value(attr, raw))

    # Cross-field: process_parameter limits should share unit with setpoint when both present.
    if schema.object_type == "process_parameter":
        issues.extend(_check_limit_units(data))

    return issues


def _validate_value(attr: AttrDef, raw: Any) -> list[AttrIssue]:
    path = attr.name
    if attr.kind == "string":
        if not isinstance(raw, str):
            return [AttrIssue("type", path, f"{path} 应为字符串")]
        return []
    if attr.kind == "boolean":
        if not isinstance(raw, bool):
            return [AttrIssue("type", path, f"{path} 应为布尔值")]
        return []
    if attr.kind == "enum":
        if attr.enum_map:
            if isinstance(raw, bool) or not isinstance(raw, str | int):
                return [AttrIssue("type", path, f"{path} 应为字符串或整数枚举码")]
            return validate_enum_raw(raw, attr.enum_map, path=path)
        if not isinstance(raw, str) or (
            attr.enum_values is not None and raw not in attr.enum_values
        ):
            allowed = ", ".join(sorted(attr.enum_values or ()))
            return [AttrIssue("enum", path, f"{path} 必须是 [{allowed}] 之一")]
        return []
    if attr.kind == "string_list":
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            return [AttrIssue("type", path, f"{path} 应为字符串数组")]
        return []
    if attr.kind == "integer":
        if isinstance(raw, bool) or not isinstance(raw, int):
            return [AttrIssue("type", path, f"{path} 应为整数")]
        return _range_issues(attr, float(raw), path)
    if attr.kind == "number":
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            return [AttrIssue("type", path, f"{path} 应为数字")]
        return _range_issues(attr, float(raw), path)
    if attr.kind == "quantity":
        return _validate_quantity(attr, raw, path)
    return [AttrIssue("type", path, f"未知属性类型 {attr.kind}")]


def _range_issues(attr: AttrDef, value: float, path: str) -> list[AttrIssue]:
    issues: list[AttrIssue] = []
    if attr.minimum is not None and value < attr.minimum:
        issues.append(
            AttrIssue("minimum", path, f"{path}={value} 低于下限 {attr.minimum}")
        )
    if attr.maximum is not None and value > attr.maximum:
        issues.append(
            AttrIssue("maximum", path, f"{path}={value} 超过上限 {attr.maximum}")
        )
    return issues


def _validate_quantity(attr: AttrDef, raw: Any, path: str) -> list[AttrIssue]:
    if not isinstance(raw, dict):
        return [
            AttrIssue(
                "type",
                path,
                f"{path} 应为数量对象 {{value, unit}}，禁止只写裸数字",
            )
        ]
    if "value" not in raw:
        return [AttrIssue("required", f"{path}.value", f"{path} 缺少 value")]
    if "unit" not in raw or raw.get("unit") in (None, ""):
        return [
            AttrIssue(
                "unit_required",
                f"{path}.unit",
                f"{path} 缺少 unit（关键量必须带单位）",
            )
        ]
    value = raw["value"]
    unit = raw["unit"]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return [AttrIssue("type", f"{path}.value", f"{path}.value 应为数字")]
    if not isinstance(unit, str):
        return [AttrIssue("type", f"{path}.unit", f"{path}.unit 应为字符串")]
    issues = _range_issues(attr, float(value), f"{path}.value")
    # allowed_units is None → any non-empty unit string OK (process parameters).
    if attr.allowed_units is not None and unit not in attr.allowed_units:
        allowed = ", ".join(sorted(attr.allowed_units))
        issues.append(
            AttrIssue(
                "unit",
                f"{path}.unit",
                f"{path}.unit={unit} 不在允许集合 [{allowed}]",
            )
        )
    return issues


def _check_limit_units(data: dict[str, Any]) -> list[AttrIssue]:
    issues: list[AttrIssue] = []
    sp = data.get("setpoint")
    if not isinstance(sp, dict) or not sp.get("unit"):
        return issues
    base = sp["unit"]
    for key in ("lower_limit", "upper_limit"):
        lim = data.get(key)
        if isinstance(lim, dict) and lim.get("unit") and lim["unit"] != base:
            issues.append(
                AttrIssue(
                    "unit_mismatch",
                    key,
                    f"{key}.unit 应与 setpoint.unit={base} 一致",
                )
            )
    return issues


def attrs_to_json_schema(schema: ObjectTypeSchema) -> dict[str, Any]:
    """Draft-07 flavoured JSON Schema for one object type's attrs object."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for attr in schema.attributes:
        properties[attr.name] = _attr_json_schema(attr)
        if attr.required:
            required.append(attr.name)
    out: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{schema.object_type}.attrs",
        "description": schema.description,
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        out["required"] = required
    return out


def _attr_json_schema(attr: AttrDef) -> dict[str, Any]:
    base: dict[str, Any] = {"description": attr.description}
    if attr.kind == "string":
        return {**base, "type": "string"}
    if attr.kind == "boolean":
        return {**base, "type": "boolean"}
    if attr.kind == "enum":
        if attr.enum_map:
            standards = sorted({e.standard for e in attr.enum_map.values()})
            return {
                **base,
                "type": "string",
                "enum": standards,
                "x-enum-map": {
                    raw: {"standard": e.standard, "label": e.label}
                    for raw, e in attr.enum_map.items()
                },
            }
        return {**base, "type": "string", "enum": sorted(attr.enum_values or ())}
    if attr.kind == "string_list":
        return {**base, "type": "array", "items": {"type": "string"}}
    if attr.kind == "integer":
        node: dict[str, Any] = {**base, "type": "integer"}
        if attr.minimum is not None:
            node["minimum"] = attr.minimum
        if attr.maximum is not None:
            node["maximum"] = attr.maximum
        return node
    if attr.kind == "number":
        node = {**base, "type": "number"}
        if attr.minimum is not None:
            node["minimum"] = attr.minimum
        if attr.maximum is not None:
            node["maximum"] = attr.maximum
        return node
    if attr.kind == "quantity":
        unit_schema: dict[str, Any] = {"type": "string", "minLength": 1}
        if attr.allowed_units is not None:
            unit_schema["enum"] = sorted(attr.allowed_units)
        value_schema: dict[str, Any] = {"type": "number"}
        if attr.minimum is not None:
            value_schema["minimum"] = attr.minimum
        if attr.maximum is not None:
            value_schema["maximum"] = attr.maximum
        return {
            **base,
            "type": "object",
            "required": ["value", "unit"],
            "additionalProperties": False,
            "properties": {"value": value_schema, "unit": unit_schema},
        }
    return base


def schema_catalog_payload() -> list[dict[str, Any]]:
    """API-friendly list of schemas with JSON Schema bodies."""
    rows: list[dict[str, Any]] = []
    for schema in list_schemas():
        rows.append(
            {
                "object_type": schema.object_type,
                "label": schema.label,
                "description": schema.description,
                "attributes": [
                    {
                        "name": a.name,
                        "kind": a.kind,
                        "required": a.required,
                        "description": a.description,
                        "unit": a.unit,
                        "allowed_units": sorted(a.allowed_units)
                        if a.allowed_units is not None
                        else None,
                        "minimum": a.minimum,
                        "maximum": a.maximum,
                        "enum_values": sorted(a.enum_values) if a.enum_values else None,
                        "enum_map": (
                            {
                                raw: {
                                    "standard": e.standard,
                                    "label": e.label,
                                    "labels": dict(e.labels) if e.labels else None,
                                }
                                for raw, e in a.enum_map.items()
                            }
                            if a.enum_map
                            else None
                        ),
                        "labels": dict(a.labels) if a.labels else None,
                    }
                    for a in schema.attributes
                ],
                "json_schema": attrs_to_json_schema(schema),
            }
        )
    return rows
