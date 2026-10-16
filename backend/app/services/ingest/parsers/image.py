"""Raster image parsers: OCR text for retrieval + keep pixels for citation preview."""

from __future__ import annotations

import io
from collections.abc import Callable

from app.services.ingest.parsers.base import ParseError, stem
from app.services.ingest.parsers.ocr import OcrEngine
from app.services.ingest.sections import Location, ParsedDocument, SectionBuilder


class ImageParser:
    """jpg/png → OCR lines as text blocks (page=1). Empty OCR still indexes a stub."""

    name = "image"

    def __init__(self, ocr_factory: Callable[[], OcrEngine | None] | None = None) -> None:
        self._ocr_factory = ocr_factory
        self._ocr: OcrEngine | None = None
        self._ocr_loaded = False

    def _engine(self) -> OcrEngine | None:
        if not self._ocr_loaded:
            self._ocr = self._ocr_factory() if self._ocr_factory else None
            self._ocr_loaded = True
        return self._ocr

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        from PIL import Image

        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except Exception as exc:
            raise ParseError(f"Cannot open image: {type(exc).__name__}: {exc}") from exc

        rgb = image.convert("RGB")
        engine = self._engine()
        if engine is None:
            raise ParseError(
                "Image OCR requires the 'ocr' package extra (rapidocr-onnxruntime)."
            )
        try:
            lines = engine.recognize(rgb)
        except Exception as exc:
            raise ParseError(f"OCR failed: {type(exc).__name__}: {exc}") from exc

        title = stem(filename)
        builder = SectionBuilder(title)
        location = Location(page=1)
        body = "\n".join(lines).strip()
        if body:
            builder.text(body, location=location)
        else:
            builder.text("（图片中未识别到文字，请结合附图查看）", location=location)
        doc = builder.build(self.name)
        doc.metadata.update(
            {
                "ocr_lines": len(lines),
                "width": rgb.width,
                "height": rgb.height,
                "format": (image.format or "").lower() or None,
            }
        )
        return doc
