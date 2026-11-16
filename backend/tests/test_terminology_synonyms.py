"""OpenSearch synonyms export from terminology aliases."""

from pathlib import Path
from types import SimpleNamespace

from app.services.terminology.synonyms import (
    BEGIN_MARKER,
    END_MARKER,
    format_synonym_lines,
    merge_synonyms_file,
    write_synonyms_file,
)


def test_format_synonym_lines_skips_single_form() -> None:
    entity = SimpleNamespace(canonical_name="织机")
    lines = format_synonym_lines([(entity, [])])  # type: ignore[arg-type]
    assert lines == []


def test_format_synonym_lines_joins_canonical_and_aliases() -> None:
    entity = SimpleNamespace(canonical_name="织机")
    aliases = [
        SimpleNamespace(alias="loom"),
        SimpleNamespace(alias="飞织机"),
        SimpleNamespace(alias="Loom"),
    ]
    lines = format_synonym_lines([(entity, aliases)])  # type: ignore[arg-type]
    assert lines == ["织机, loom, 飞织机"]


def test_format_drops_comma_tokens() -> None:
    entity = SimpleNamespace(canonical_name="ACL")
    aliases = [SimpleNamespace(alias="访问控制列表"), SimpleNamespace(alias="bad,token")]
    lines = format_synonym_lines([(entity, aliases)])  # type: ignore[arg-type]
    assert lines == ["ACL, 访问控制列表"]


def test_merge_preserves_manual_and_replaces_managed(tmp_path: Path) -> None:
    path = tmp_path / "synonyms.txt"
    path.write_text(
        "# header\n报销, 费用报销\n\n"
        f"{BEGIN_MARKER}\nold, alias\n{END_MARKER}\n"
        "# footer note\n",
        encoding="utf-8",
    )
    write_synonyms_file(path, ["织机, loom", "防火墙, firewall"])
    text = path.read_text(encoding="utf-8")
    assert "报销, 费用报销" in text
    assert "footer note" in text
    assert "old, alias" not in text
    assert "织机, loom" in text
    assert text.index(BEGIN_MARKER) < text.index("织机") < text.index(END_MARKER)


def test_merge_appends_markers_when_missing() -> None:
    merged = merge_synonyms_file("# seed\n人力资源, HR\n", ["VPN, 虚拟专用网"])
    assert "# seed" in merged
    assert BEGIN_MARKER in merged and END_MARKER in merged
    assert "VPN, 虚拟专用网" in merged
