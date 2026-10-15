"""Size capping of retrieval trace stages before they are stored in PG."""

import copy
import json
from typing import Any

# (path to a list inside the stages document) - longest lists are cut first.
TRUNCATABLE: tuple[tuple[str, ...], ...] = (
    ("routes", "dense", "hits"),
    ("routes", "sparse", "hits"),
    ("fusion", "candidates"),
    ("rerank", "scores"),
    ("results",),
)


def _size(doc: dict[str, Any]) -> int:
    return len(json.dumps(doc, ensure_ascii=False, default=str).encode("utf-8"))


def _get_list(doc: dict[str, Any], path: tuple[str, ...]) -> list[Any] | None:
    node: Any = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, list) else None


def truncate_stages(stages: dict[str, Any], max_bytes: int) -> tuple[dict[str, Any], bool]:
    """Halve candidate lists until the serialized document fits; drop them as a last resort."""
    if _size(stages) <= max_bytes:
        return stages, False
    doc = copy.deepcopy(stages)
    lists = [(path, lst) for path in TRUNCATABLE if (lst := _get_list(doc, path)) is not None]
    limit = max((len(lst) for _, lst in lists), default=0)
    while limit > 1 and _size(doc) > max_bytes:
        limit //= 2
        for _, lst in lists:
            del lst[limit:]
    if _size(doc) > max_bytes:
        for _, lst in lists:
            lst.clear()
    if _size(doc) > max_bytes:
        doc = {key: doc[key] for key in ("query",) if key in doc}
        doc["query"] = {"text": str(doc.get("query", {}).get("text", ""))[:500]}
    doc["truncated"] = True
    return doc, True
