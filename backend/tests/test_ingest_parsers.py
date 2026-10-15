from typing import Any

import pytest

from app.core.config import Settings
from app.services.ingest.parsers import ParseError, ParserRegistry
from app.services.ingest.parsers.base import FileKind, decode_text, detect_kind
from app.services.ingest.parsers.pdf import BasicPdfParser
from app.services.ingest.sections import ParsedDocument, Section
from tests.samples import (
    TABLE_HEADER,
    make_docx,
    make_markdown,
    make_pdf,
    make_pptx,
    make_xlsx,
)


def titles(section: Section) -> list[str]:
    """Heading titles below the document root, depth-first."""
    out: list[str] = []
    for child in section.children:
        out += [child.title or "", *titles(child)]
    return out


@pytest.fixture
def registry(settings: Settings) -> ParserRegistry:
    basic = settings.model_copy(update={"pdf_parser": "basic", "ocr_enabled": False})
    return ParserRegistry(basic)


def test_detect_kind_prefers_extension_then_mime() -> None:
    assert detect_kind("a.DOCX") is FileKind.WORD
    assert detect_kind("report", "application/pdf") is FileKind.PDF
    assert detect_kind("x.exe", "application/octet-stream") is None


def test_decode_text_handles_gbk() -> None:
    assert decode_text("中文内容".encode("gb18030")) == "中文内容"
    assert decode_text("\ufeffhello".encode()) == "hello"


def test_word_keeps_heading_hierarchy_and_tables(registry: ParserRegistry) -> None:
    doc = registry.parse(make_docx(10), "handbook.docx")
    assert doc.parser == "docx"
    chapter1 = doc.root.children[0]
    assert chapter1.title == "第一章 总则"
    assert [c.title for c in chapter1.children] == ["1.1 适用范围", "1.2 术语"]
    tables = [b.table for b in doc.iter_blocks() if b.table is not None]
    assert len(tables) == 1
    assert tables[0].header == TABLE_HEADER
    assert len(tables[0].rows) == 10


def test_excel_one_section_per_sheet(registry: ParserRegistry) -> None:
    doc = registry.parse(make_xlsx(30), "stock.xlsx")
    assert [s.title for s in doc.root.children] == ["库存", "汇总"]
    stock = doc.root.children[0]
    table = stock.blocks[0].table
    assert table is not None and table.header == TABLE_HEADER and len(table.rows) == 30
    assert stock.blocks[0].location.sheet == "库存"
    assert doc.metadata["sheets"] == ["库存", "汇总"]


def test_powerpoint_slides_with_notes_and_tables(registry: ParserRegistry) -> None:
    doc = registry.parse(make_pptx(), "review.pptx")
    assert [s.title for s in doc.root.children] == ["季度经营回顾", "区域销售数据", "下季度计划"]
    first = doc.root.children[0]
    texts = " ".join(b.content for b in first.blocks)
    assert "营收同比增长" in texts and "备注" in texts and "华东区贡献最大" in texts
    assert all(b.location.slide == 1 for b in first.blocks)
    table = next(b.table for b in doc.root.children[1].blocks if b.table is not None)
    assert table.header == ["区域", "销售额", "同比"]


def test_markdown_headings_and_pipe_tables(registry: ParserRegistry) -> None:
    doc = registry.parse(make_markdown(), "deploy.md")
    assert titles(doc.root) == ["部署指南", "环境要求", "配置项", "常见问题"]
    table = next(b.table for b in doc.iter_blocks() if b.table is not None)
    assert table.header == ["名称", "默认值", "说明"]
    assert table.rows[0][0] == "PDF_PARSER"


def test_html_parser(registry: ParserRegistry) -> None:
    html = (
        "<html><body><h1>标题</h1><p>第一段</p><h2>小节</h2><ul><li>要点A</li></ul>"
        "<table><tr><th>名称</th><th>值</th></tr><tr><td>a</td><td>1</td></tr></table>"
        "<script>ignored()</script></body></html>"
    )
    doc = registry.parse(html.encode(), "page.html")
    assert titles(doc.root) == ["标题", "小节"]
    content = " ".join(b.content for b in doc.iter_blocks())
    assert "第一段" in content and "要点A" in content and "ignored" not in content
    assert any(b.table is not None for b in doc.iter_blocks())


def test_pdf_headings_by_font_size_and_tables(registry: ParserRegistry) -> None:
    doc = registry.parse(make_pdf(), "guide.pdf")
    assert doc.parser == "pdfplumber"
    assert {"1 Overview", "1.1 Scope", "2 Prices"} <= set(titles(doc.root))
    tables = [b for b in doc.iter_blocks() if b.table is not None]
    assert tables, "the bordered table should be detected"
    table = tables[0].table
    assert table is not None and table.header[0] == "Code" and len(table.rows) == 15
    assert tables[0].location.page == 2
    # Table cells are not duplicated as loose text.
    loose = " ".join(b.text for b in doc.iter_blocks() if b.table is None)
    assert "M-0007" not in loose


def _scanned_pdf() -> bytes:
    from fpdf import FPDF
    from PIL import Image

    pdf = FPDF()
    pdf.add_page()
    pdf.image(Image.new("RGB", (400, 200), "white"), x=10, y=10, w=150)
    return bytes(pdf.output())


class FakeOcr:
    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, image: Any) -> list[str]:
        self.calls += 1
        return ["扫描件第一行", "扫描件第二行"]


def test_scanned_pdf_uses_ocr() -> None:
    ocr = FakeOcr()
    doc = BasicPdfParser(lambda: ocr).parse(_scanned_pdf(), "scan.pdf")
    assert ocr.calls == 1
    assert doc.metadata["ocr_pages"] == [1]
    assert "扫描件第一行" in " ".join(b.text for b in doc.iter_blocks())


def test_scanned_pdf_without_ocr_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        BasicPdfParser(None).parse(_scanned_pdf(), "scan.pdf")


def test_unsupported_and_corrupt_files(registry: ParserRegistry) -> None:
    with pytest.raises(ParseError):
        registry.parse(b"MZ...", "tool.exe")
    with pytest.raises(ParseError):
        registry.parse(b"not a zip", "broken.docx")


def test_parsed_document_round_trip(registry: ParserRegistry) -> None:
    doc = registry.parse(make_docx(5), "handbook.docx")
    restored = ParsedDocument.from_dict(doc.to_dict())
    assert restored.to_dict() == doc.to_dict()
