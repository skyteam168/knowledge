"""Burn a tiled, rotated text watermark into page images (server side, so it survives saving)."""

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# CJK-capable fonts, first found wins (container packages, then desktop systems for local runs).
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
)
ANGLE = 30
OPACITY = 56
COLOR = (110, 110, 110)

FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont


@lru_cache(maxsize=8)
def _font(size: int) -> FontType:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _tile(lines: list[str], size: int) -> Image.Image:
    font = _font(size)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    boxes = [probe.textbbox((0, 0), line, font=font) for line in lines]
    width = int(max(b[2] - b[0] for b in boxes))
    line_height = int(max(b[3] - b[1] for b in boxes)) + size // 3
    tile = Image.new("RGBA", (width + size * 4, line_height * len(lines) + size * 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    for i, line in enumerate(lines):
        draw.text((size * 2, size * 2 + i * line_height), line, font=font, fill=(*COLOR, OPACITY))
    return tile.rotate(ANGLE, expand=True, resample=Image.Resampling.BICUBIC)


def watermark_png(data: bytes, lines: list[str]) -> bytes:
    """PNG `data` with `lines` tiled diagonally over the whole image."""
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    size = max(14, min(image.size) // 40)
    tile = _tile([line for line in lines if line] or ["-"], size)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    for row, y in enumerate(range(-tile.height // 2, image.height, tile.height)):
        offset = (tile.width // 2) * (row % 2)
        for x in range(-tile.width + offset, image.width, tile.width):
            overlay.alpha_composite(tile, (max(x, 0), max(y, 0)), (max(-x, 0), max(-y, 0)))
    out = io.BytesIO()
    Image.alpha_composite(image, overlay).convert("RGB").save(out, format="PNG")
    return out.getvalue()
