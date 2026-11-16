"""Page-image extract result metadata used by ingest + missing-pages filters."""

from __future__ import annotations

from app.services.ingest.page_images import (
    extract_page_images_result,
    page_image_expected,
)


def test_page_image_expected_by_extension() -> None:
    assert page_image_expected("a.PDF") is True
    assert page_image_expected("deck.pptx") is True
    assert page_image_expected("notes.md") is False


def test_extract_result_unsupported_not_expected() -> None:
    result = extract_page_images_result(b"hello", "readme.txt")
    assert result.expected is False
    assert result.images == []
    assert result.error is None


def test_extract_result_records_error_on_bad_pdf() -> None:
    result = extract_page_images_result(b"not-a-pdf", "broken.pdf")
    assert result.expected is True
    assert result.images == []
    assert result.error
