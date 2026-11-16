"""Idempotent IT-ops sample terminology for local / demo orgs."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    TerminologyAlias,
    TerminologyEntity,
    TerminologyEntityType,
    TerminologyLang,
    TerminologyStatus,
)
from app.services.terminology.expander import normalize_alias


@dataclass(frozen=True)
class SeedTerm:
    canonical_name: str
    entity_type: str
    aliases: tuple[str, ...]
    description: str


IT_OPS_SEED: tuple[SeedTerm, ...] = (
    SeedTerm(
        "交换机",
        TerminologyEntityType.IT_TERM.value,
        ("switch", "网络交换机", "cisco switch", "思科交换机"),
        "网络交换设备",
    ),
    SeedTerm(
        "ACL",
        TerminologyEntityType.IT_TERM.value,
        ("访问控制列表", "access control list", "访问控制"),
        "交换机/防火墙访问控制列表",
    ),
    SeedTerm(
        "VLAN",
        TerminologyEntityType.IT_TERM.value,
        ("虚拟局域网", "virtual lan"),
        "虚拟局域网分段",
    ),
    SeedTerm(
        "SMTP",
        TerminologyEntityType.IT_TERM.value,
        ("邮件发送协议", "简单邮件传输协议", "smtp server"),
        "发送邮件协议",
    ),
    SeedTerm(
        "邮件退信",
        TerminologyEntityType.IT_TERM.value,
        ("bounce", "退信", "mail bounce", "发送失败"),
        "邮件发送失败/退回",
    ),
    SeedTerm(
        "DNS",
        TerminologyEntityType.IT_TERM.value,
        ("域名系统", "domain name system", "域名解析"),
        "域名解析服务",
    ),
    SeedTerm(
        "VPN",
        TerminologyEntityType.IT_TERM.value,
        ("虚拟专用网络", "virtual private network"),
        "远程接入虚拟专用网",
    ),
    SeedTerm(
        "防火墙",
        TerminologyEntityType.IT_TERM.value,
        ("firewall", "安全网关"),
        "网络边界防护设备",
    ),
    SeedTerm(
        "LDAP",
        TerminologyEntityType.IT_TERM.value,
        ("目录服务", "active directory", "AD"),
        "目录与账号认证相关",
    ),
    SeedTerm(
        "备份",
        TerminologyEntityType.PROCESS.value,
        ("backup", "数据备份", "灾难恢复", "DR"),
        "数据备份与恢复",
    ),
)


async def seed_it_ops(session: AsyncSession, org_id: str) -> dict[str, int]:
    """Upsert sample IT terms by canonical_name within the org. Returns counts."""
    created = 0
    updated = 0
    aliases_added = 0
    for term in IT_OPS_SEED:
        existing = await session.scalar(
            select(TerminologyEntity).where(
                TerminologyEntity.org_id == org_id,
                TerminologyEntity.canonical_name == term.canonical_name,
            )
        )
        if existing is None:
            entity = TerminologyEntity(
                org_id=org_id,
                canonical_name=term.canonical_name,
                entity_type=term.entity_type,
                description=term.description,
                status=TerminologyStatus.ACTIVE.value,
            )
            session.add(entity)
            await session.flush()
            created += 1
        else:
            entity = existing
            entity.entity_type = term.entity_type
            entity.description = term.description
            entity.status = TerminologyStatus.ACTIVE.value
            updated += 1

        forms = [term.canonical_name, *term.aliases]
        for form in forms:
            norm = normalize_alias(form)
            if not norm:
                continue
            found = await session.scalar(
                select(TerminologyAlias).where(
                    TerminologyAlias.org_id == org_id,
                    TerminologyAlias.alias_normalized == norm,
                )
            )
            if found is None:
                session.add(
                    TerminologyAlias(
                        org_id=org_id,
                        entity_id=entity.id,
                        alias=form,
                        alias_normalized=norm,
                        lang=TerminologyLang.ANY.value,
                    )
                )
                aliases_added += 1
            elif found.entity_id != entity.id:
                # Collision with another entity — skip rather than steal.
                continue
    await session.flush()
    return {"created": created, "updated": updated, "aliases_added": aliases_added}
