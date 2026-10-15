import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class OcrEngine(Protocol):
    def recognize(self, image: Any) -> list[str]:
        """Text lines of a PIL image, in reading order."""
        ...


class RapidOcrEngine:
    """PP-OCR models via onnxruntime (`ocr` extra); handles Chinese and English."""

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        self._engine = RapidOCR()

    def recognize(self, image: Any) -> list[str]:
        import numpy as np

        result, _ = self._engine(np.asarray(image.convert("RGB")))
        if not result:
            return []
        # result: [[box, text, score], ...]; sort top-to-bottom, then left-to-right.
        ordered = sorted(result, key=lambda r: (round(r[0][0][1] / 10), r[0][0][0]))
        return [str(r[1]).strip() for r in ordered if str(r[1]).strip()]


def load_ocr_engine() -> OcrEngine | None:
    try:
        return RapidOcrEngine()
    except ImportError:
        logger.warning("ocr_unavailable", extra={"hint": "install the 'ocr' extra"})
        return None
