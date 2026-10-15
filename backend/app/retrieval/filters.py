from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.retrieval.query import QueryFilters
from app.services.authz.acl import AclFilter


@dataclass(frozen=True)
class SearchFilter:
    """ACL pre-filter (tenant + principals + kb scope) plus the user's own filters.

    The tenant / principal conditions come only from `acl`; user filters can narrow the
    result set further but never widen it. `date_to` is exclusive.
    """

    acl: AclFilter
    tags: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()
    date_from: datetime | None = None
    date_to: datetime | None = None

    @classmethod
    def of(cls, acl: AclFilter, filters: QueryFilters) -> "SearchFilter":
        return cls(
            acl=acl,
            tags=tuple(sorted(set(filters.tags))),
            doc_types=tuple(sorted(set(filters.doc_types))),
            date_from=filters.date_from,
            date_to=filters.date_to,
        )

    def _range(self) -> dict[str, str]:
        bounds: dict[str, str] = {}
        if self.date_from is not None:
            bounds["gte"] = self.date_from.isoformat()
        if self.date_to is not None:
            bounds["lt"] = self.date_to.isoformat()
        return bounds

    def to_qdrant(self) -> dict[str, Any]:
        must = list(self.acl.to_qdrant()["must"])
        if self.tags:
            must.append({"key": "tags", "match": {"any": list(self.tags)}})
        if self.doc_types:
            must.append({"key": "doc_type", "match": {"any": list(self.doc_types)}})
        if bounds := self._range():
            must.append({"key": "created_at", "range": bounds})
        return {"must": must}

    def to_opensearch(self) -> list[dict[str, Any]]:
        """bool.filter clauses."""
        clauses = list(self.acl.to_opensearch()["bool"]["filter"])
        if self.tags:
            clauses.append({"terms": {"tags": list(self.tags)}})
        if self.doc_types:
            clauses.append({"terms": {"doc_type": list(self.doc_types)}})
        if bounds := self._range():
            clauses.append({"range": {"created_at": bounds}})
        return clauses

    def describe(self) -> dict[str, Any]:
        return {
            "org_id": self.acl.org_id,
            "kb_ids": list(self.acl.kb_ids),
            "bypass_acl": self.acl.bypass_acl,
            "principals": len(self.acl.principals),
            "tags": list(self.tags),
            "doc_types": list(self.doc_types),
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
        }
