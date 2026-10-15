from app.core.exceptions import NotFoundError
from app.repositories.base import paginate
from app.repositories.search_repo import RetrievalTraceRepository
from app.schemas.common import Page
from app.schemas.search import RetrievalTraceOut, RetrievalTraceSummaryOut
from app.services.context import BaseService


class RetrievalTraceService(BaseService):
    async def list(
        self,
        *,
        page: int,
        size: int,
        user_id: str | None = None,
        keyword: str | None = None,
        degraded_only: bool = False,
    ) -> Page[RetrievalTraceSummaryOut]:
        stmt = RetrievalTraceRepository.search_stmt(
            self.org_id, user_id=user_id, keyword=keyword, degraded_only=degraded_only
        )
        rows, total = await paginate(self.session, stmt, page, size)
        return Page(
            items=[RetrievalTraceSummaryOut.model_validate(r) for r in rows],
            total=total,
            page=page,
            size=size,
        )

    async def get(self, trace_id: str) -> RetrievalTraceOut:
        trace = await RetrievalTraceRepository(self.session).get(self.org_id, trace_id)
        if trace is None:
            raise NotFoundError("Retrieval trace not found")
        return RetrievalTraceOut.model_validate(trace)
