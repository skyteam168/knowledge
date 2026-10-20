"""Document protection: watermark, copy protection and who may download the original file.

The knowledge base sets the policy; a document's own settings combine with it by OR (flags) and
max (download permission), so a document can only make protection stricter, never looser.
"""

from dataclasses import dataclass
from typing import Literal

from app.models import Document, KnowledgeBase

DownloadPermission = Literal["read", "edit", "manage"]
ORDER: tuple[DownloadPermission, ...] = ("read", "edit", "manage")
LEVELS: dict[str, int] = {name: i + 1 for i, name in enumerate(ORDER)}
# Hint returned when Open API / export strips body text for a controlled document.
CONTROLLED_EXPORT_HINT = "（受控预览：正文已截断，请在站内查看原文）"


@dataclass(frozen=True)
class Protection:
    watermark: bool = False
    copy_protect: bool = False
    download_permission: DownloadPermission = "read"

    def can_download(self, permission: str | None) -> bool:
        return permission is not None and LEVELS[permission] >= LEVELS[self.download_permission]

    def raw_preview(self, permission: str | None) -> bool:
        """The original file may be shown inline (a viewer can always save what it shows)."""
        return not self.watermark and self.can_download(permission)

    def limits_export(self, permission: str | None) -> bool:
        """Outward text (API snippets, citation quotes) should be shortened for this viewer."""
        return self.copy_protect or not self.can_download(permission)


def _stricter(a: str, b: str | None) -> DownloadPermission:
    return ORDER[max(LEVELS.get(a, 1), LEVELS.get(b or "read", 1)) - 1]


def protection_of(kb: KnowledgeBase, doc: Document | None = None) -> Protection:
    return Protection(
        watermark=bool(kb.watermark or (doc is not None and doc.watermark)),
        copy_protect=bool(kb.copy_protect or (doc is not None and doc.copy_protect)),
        download_permission=_stricter(
            kb.download_permission, doc.download_permission if doc else None
        ),
    )


def limit_export_text(text: str, max_chars: int, *, ellipsis: str = "…") -> str:
    """Truncate outward-facing text; empty when max_chars <= 0."""
    if max_chars <= 0:
        return ""
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    keep = max(0, max_chars - len(ellipsis))
    return cleaned[:keep].rstrip() + ellipsis
