from itertools import pairwise

from app.core.config import Settings
from app.services.ingest.chunker import (
    CHILD_LEVEL,
    PARENT_LEVEL,
    ChunkDraft,
    Chunker,
    ChunkingConfig,
)
from app.services.ingest.parsers import ParserRegistry
from app.services.ingest.sections import SectionBuilder, TableData
from app.services.ingest.tokens import count_tokens
from tests.samples import LOREM_ZH, TABLE_HEADER, make_docx, make_pptx, make_xlsx, table_rows

CONFIG = ChunkingConfig()


def parse(settings: Settings, data: bytes, filename: str):  # type: ignore[no-untyped-def]
    return ParserRegistry(settings.model_copy(update={"pdf_parser": "basic"})).parse(data, filename)


def parents(drafts: list[ChunkDraft]) -> list[ChunkDraft]:
    return [d for d in drafts if d.level == PARENT_LEVEL]


def children(drafts: list[ChunkDraft]) -> list[ChunkDraft]:
    return [d for d in drafts if d.level == CHILD_LEVEL]


def test_token_estimate() -> None:
    assert count_tokens("中文四字") == 4
    assert count_tokens("") == 0
    assert 5 <= count_tokens("hello world from the pipeline") <= 8


def test_structure_seq_and_parent_links(settings: Settings) -> None:
    drafts = Chunker(CONFIG).chunk(parse(settings, make_docx(60), "handbook.docx"))
    assert [d.seq for d in drafts] == list(range(len(drafts)))
    parent_seqs = {d.seq for d in parents(drafts)}
    assert parent_seqs
    for child in children(drafts):
        assert child.parent_seq in parent_seqs
        parent = drafts[child.parent_seq]
        # A child's heading path is within its parent's section.
        assert child.heading_path[: len(parent.heading_path)] == parent.heading_path


def test_size_limits(settings: Settings) -> None:
    drafts = Chunker(CONFIG).chunk(parse(settings, make_docx(200), "handbook.docx"))
    for child in children(drafts):
        assert child.token_count <= CONFIG.child_max + CONFIG.child_overlap
    for parent in parents(drafts):
        assert parent.token_count <= CONFIG.parent_max * 1.3


def test_large_table_split_into_row_groups_with_header(settings: Settings) -> None:
    drafts = Chunker(CONFIG).chunk(parse(settings, make_xlsx(300), "stock.xlsx"))
    header_line = "| " + " | ".join(TABLE_HEADER) + " |"
    tables = [d for d in children(drafts) if d.chunk_type == "table" and d.sheet_name == "库存"]
    assert len(tables) > 1
    seen: list[str] = []
    for chunk in tables:
        lines = chunk.content.splitlines()
        assert lines[0] == header_line
        assert set(lines[1].replace("|", "").strip()) <= {"-", " "}
        for line in lines[2:]:
            # Every row is complete: 5 cells, never cut in the middle.
            assert line.startswith("| M-") and line.count("|") == len(TABLE_HEADER) + 1
            seen.append(line.split("|")[1].strip())
    assert seen == [r[0] for r in table_rows(300)]


def test_small_table_stays_whole() -> None:
    builder = SectionBuilder("doc")
    builder.heading("价格", 1)
    builder.text(LOREM_ZH)
    builder.table(TableData(header=TABLE_HEADER, rows=table_rows(8)))
    builder.text(LOREM_ZH)
    drafts = Chunker(CONFIG).chunk(builder.build("test"))
    tables = [d for d in children(drafts) if d.chunk_type == "table"]
    assert len(tables) == 1
    assert tables[0].content.count("| M-") == 8
    assert tables[0].heading_path == ["价格"]


def test_long_text_children_overlap() -> None:
    builder = SectionBuilder("doc")
    builder.heading("长文", 1)
    for _ in range(12):
        builder.text(LOREM_ZH * 2)
    drafts = Chunker(CONFIG).chunk(builder.build("test"))
    kids = children(drafts)
    assert len(kids) >= 3
    for prev, nxt in pairwise(kids):
        last_sentence = prev.content.rstrip().split("。")[-2]
        assert last_sentence in nxt.content


def test_slides_do_not_mix_in_one_child(settings: Settings) -> None:
    drafts = Chunker(CONFIG).chunk(parse(settings, make_pptx(), "review.pptx"))
    kids = children(drafts)
    assert {k.slide_number for k in kids} == {1, 2, 3}
    for kid in kids:
        assert kid.heading_path and kid.heading_path[0] in {
            "季度经营回顾",
            "区域销售数据",
            "下季度计划",
        }


def test_configurable_sizes(settings: Settings) -> None:
    doc = parse(settings, make_docx(60), "handbook.docx")
    small = ChunkingConfig(
        parent_target=400, parent_max=600, child_target=100, child_max=150, child_overlap=20
    )
    assert len(Chunker(small).chunk(doc)) > len(Chunker(CONFIG).chunk(doc))
