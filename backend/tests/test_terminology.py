"""Terminology entities, alias expander, and admin CRUD."""

from app.core.config import Settings
from app.services.terminology.expander import (
    AliasEntry,
    build_alias_index,
    expand_queries,
    match_entity_ids,
    merge_search_text,
    normalize_alias,
)
from app.services.terminology.tagger import tag_texts


def test_normalize_alias() -> None:
    assert normalize_alias("  ACL  ") == "acl"
    assert normalize_alias("访问控制列表") == "访问控制列表"


def test_expand_queries_injects_canonical_and_aliases() -> None:
    entries = [
        AliasEntry(
            entity_id="e1",
            canonical_name="ACL",
            forms=("ACL", "访问控制列表", "access control list"),
        )
    ]
    result = expand_queries(["如何配置访问控制列表"], entries, max_extra=3)
    assert result.original == ["如何配置访问控制列表"]
    assert "ACL" in result.queries
    assert any(
        "access control list" in q.lower() or q == "access control list" for q in result.queries
    )
    assert result.matches and result.matches[0]["canonical_name"] == "ACL"


def test_expand_respects_max_extra() -> None:
    entries = [
        AliasEntry(
            entity_id="e1",
            canonical_name="交换机",
            forms=("交换机", "switch", "网络交换机", "cisco switch"),
        )
    ]
    result = expand_queries(["交换机端口配置"], entries, max_extra=1)
    extras = [q for q in result.queries if q != "交换机端口配置"]
    assert len(extras) == 1


def test_disabled_style_entries_not_passed() -> None:
    # Expander only sees what the service loads; empty entries => no expansion.
    result = expand_queries(["ACL 配置"], [], max_extra=3)
    assert result.queries == ["ACL 配置"]
    assert result.matches == []


def test_ascii_boundary_avoids_inner_match() -> None:
    entries = [
        AliasEntry(entity_id="e1", canonical_name="VPN", forms=("VPN",)),
    ]
    result = expand_queries(["devpntool"], entries, max_extra=3)
    assert result.matches == []
    assert result.queries == ["devpntool"]


def test_merge_search_text() -> None:
    expansion = expand_queries(
        ["配置交换机"],
        [AliasEntry("e1", "交换机", ("交换机", "switch"))],
        max_extra=2,
    )
    merged = merge_search_text("配置交换机", expansion)
    assert "配置交换机" in merged
    assert "switch" in merged.lower()


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.terminology_expand_enabled is True
    assert settings.terminology_expand_max_extra == 3
    assert settings.chat_expand_entity_limit == 2


def test_match_entity_ids_tags_aliases() -> None:
    entries = [
        AliasEntry(
            entity_id="e-fw",
            canonical_name="防火墙",
            forms=("防火墙", "firewall", "安全网关"),
        ),
        AliasEntry(entity_id="e-vpn", canonical_name="VPN", forms=("VPN", "虚拟专用网络")),
    ]
    index = build_alias_index(entries)
    assert match_entity_ids("配置 firewall 与 VPN", index) == ["e-fw", "e-vpn"]
    assert match_entity_ids("无关文本", index) == []
    assert tag_texts(["安全网关策略", "hello"], index) == [["e-fw"], []]
