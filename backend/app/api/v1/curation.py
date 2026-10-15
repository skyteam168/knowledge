from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import (
    AuthzCacheDep,
    DbSessionDep,
    RequestContextDep,
    ResourcesDep,
    SettingsDep,
    provide,
    require_permission,
)
from app.models import GapStatus, GapType, KoStatus, KoType, ReviewStatus
from app.retrieval.pipeline import RetrievalPipeline
from app.schemas.common import Page
from app.schemas.curation import (
    ClusterRunOut,
    FaqGenerateIn,
    GapClusterOut,
    GapDetailOut,
    GapDraftIn,
    GapDuplicateIn,
    GapLinkDocumentsIn,
    GapOut,
    GapPatch,
    GapRejectIn,
    GapSort,
    GapStatsOut,
    KoCreate,
    KoDeprecateIn,
    KoDetailOut,
    KoOut,
    KoReviewIn,
    KoSubmitIn,
    KoUpdate,
    KoVersionOut,
    ReviewTaskOut,
)
from app.schemas.knowledge import DocumentAclOut, DocumentAclUpdate
from app.services.curation.clustering import GapClusterer
from app.services.curation.gap_service import GapService
from app.services.curation.ko_service import KnowledgeObjectService

GAP_REVIEW = "gap:review"
KO_EDIT = "ko:edit"
REVIEW_APPROVE = "review:approve"

router = APIRouter(
    prefix="/curation",
    tags=["curation"],
    dependencies=[Depends(require_permission(GAP_REVIEW, KO_EDIT, REVIEW_APPROVE))],
)


def get_ko_service(
    session: DbSessionDep,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> KnowledgeObjectService:
    return KnowledgeObjectService(
        session,
        ctx,
        cache,
        pipeline=RetrievalPipeline.build(
            resources.indexing.backends, resources.llm, resources.cache
        ),
        gateway=resources.llm,
        settings=settings,
    )


GapServiceDep = Annotated[GapService, Depends(provide(GapService))]
KoServiceDep = Annotated[KnowledgeObjectService, Depends(get_ko_service)]
GapReviewer = Depends(require_permission(GAP_REVIEW))
KoEditor = Depends(require_permission(KO_EDIT))
Reviewer = Depends(require_permission(REVIEW_APPROVE))

# ---- gaps ---------------------------------------------------------------------------------


@router.get("/gaps", response_model=Page[GapOut], dependencies=[GapReviewer])
async def list_gaps(
    service: GapServiceDep,
    status: Annotated[list[GapStatus] | None, Query()] = None,
    gap_type: GapType | None = None,
    kb_id: Annotated[str | None, Query(max_length=32)] = None,
    cluster_id: Annotated[str | None, Query(max_length=32)] = None,
    assignee_id: Annotated[str | None, Query(max_length=32)] = None,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    sort: GapSort = "frequency",
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[GapOut]:
    return await service.list_page(
        statuses=[s.value for s in status or []],
        gap_type=gap_type.value if gap_type else None,
        kb_id=kb_id,
        cluster_id=cluster_id,
        assignee_id=assignee_id,
        keyword=keyword,
        sort=sort,
        page=page,
        size=size,
    )


@router.get("/gaps/stats", response_model=GapStatsOut, dependencies=[GapReviewer])
async def gap_stats(service: GapServiceDep) -> GapStatsOut:
    return await service.stats()


@router.get("/gap-clusters", response_model=Page[GapClusterOut], dependencies=[GapReviewer])
async def list_clusters(
    service: GapServiceDep,
    kb_id: Annotated[str | None, Query(max_length=32)] = None,
    open_only: bool = True,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[GapClusterOut]:
    return await service.clusters(kb_id=kb_id, open_only=open_only, page=page, size=size)


@router.post("/gap-clusters/run", response_model=ClusterRunOut, dependencies=[GapReviewer])
async def run_clustering(
    ctx: RequestContextDep, resources: ResourcesDep, settings: SettingsDep
) -> ClusterRunOut:
    """Cluster the organization's pending gaps now (the scheduler does it periodically)."""
    clusterer = GapClusterer(resources.session_factory, resources.llm, settings)
    return await clusterer.run_once(ctx.org_id)


@router.get("/gaps/{gap_id}", response_model=GapDetailOut, dependencies=[GapReviewer])
async def get_gap(gap_id: str, service: GapServiceDep) -> GapDetailOut:
    return await service.detail(gap_id)


@router.patch("/gaps/{gap_id}", response_model=GapOut, dependencies=[GapReviewer])
async def patch_gap(gap_id: str, data: GapPatch, service: GapServiceDep) -> GapOut:
    return await service.patch(gap_id, data)


@router.post("/gaps/{gap_id}/link-documents", response_model=GapOut, dependencies=[GapReviewer])
async def link_documents(gap_id: str, data: GapLinkDocumentsIn, service: GapServiceDep) -> GapOut:
    return await service.link_documents(gap_id, data)


@router.post("/gaps/{gap_id}/reject", response_model=GapOut, dependencies=[GapReviewer])
async def reject_gap(gap_id: str, data: GapRejectIn, service: GapServiceDep) -> GapOut:
    return await service.reject(gap_id, data.note)


@router.post("/gaps/{gap_id}/duplicate", response_model=GapOut, dependencies=[GapReviewer])
async def duplicate_gap(gap_id: str, data: GapDuplicateIn, service: GapServiceDep) -> GapOut:
    return await service.mark_duplicate(gap_id, data)


@router.post("/gaps/{gap_id}/reopen", response_model=GapOut, dependencies=[GapReviewer])
async def reopen_gap(gap_id: str, service: GapServiceDep) -> GapOut:
    return await service.reopen(gap_id)


@router.post(
    "/gaps/{gap_id}/draft",
    response_model=KoDetailOut,
    status_code=201,
    dependencies=[GapReviewer, KoEditor],
)
async def draft_from_gap(gap_id: str, data: GapDraftIn, service: KoServiceDep) -> KoDetailOut:
    return await service.draft_from_gap(gap_id, data)


# ---- knowledge objects -------------------------------------------------------------------


@router.get("/kos", response_model=Page[KoOut])
async def list_kos(
    service: KoServiceDep,
    kb_id: Annotated[str | None, Query(max_length=32)] = None,
    status: KoStatus | None = None,
    ko_type: KoType | None = None,
    owner_id: Annotated[str | None, Query(max_length=32)] = None,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[KoOut]:
    return await service.list_page(
        kb_id=kb_id,
        status=status.value if status else None,
        ko_type=ko_type.value if ko_type else None,
        owner_id=owner_id,
        keyword=keyword,
        page=page,
        size=size,
    )


@router.post("/kos", response_model=KoDetailOut, status_code=201, dependencies=[KoEditor])
async def create_ko(data: KoCreate, service: KoServiceDep) -> KoDetailOut:
    return await service.create(data)


@router.get("/kos/{ko_id}", response_model=KoDetailOut)
async def get_ko(ko_id: str, service: KoServiceDep) -> KoDetailOut:
    return await service.get(ko_id)


@router.put("/kos/{ko_id}", response_model=KoDetailOut, dependencies=[KoEditor])
async def update_ko(ko_id: str, data: KoUpdate, service: KoServiceDep) -> KoDetailOut:
    return await service.update(ko_id, data)


@router.post("/kos/{ko_id}/submit", response_model=KoDetailOut, dependencies=[KoEditor])
async def submit_ko(ko_id: str, data: KoSubmitIn, service: KoServiceDep) -> KoDetailOut:
    return await service.submit(ko_id, data.note)


@router.post("/kos/{ko_id}/withdraw", response_model=KoDetailOut, dependencies=[KoEditor])
async def withdraw_ko(ko_id: str, service: KoServiceDep) -> KoDetailOut:
    return await service.withdraw(ko_id)


@router.post("/kos/{ko_id}/review", response_model=KoDetailOut, dependencies=[Reviewer])
async def review_ko(ko_id: str, data: KoReviewIn, service: KoServiceDep) -> KoDetailOut:
    return await service.review(ko_id, data.decision == "approve", data.comment)


@router.post("/kos/{ko_id}/deprecate", response_model=KoDetailOut, dependencies=[KoEditor])
async def deprecate_ko(ko_id: str, data: KoDeprecateIn, service: KoServiceDep) -> KoDetailOut:
    return await service.deprecate(ko_id, data.reason)


@router.post("/kos/{ko_id}/check-conflicts", response_model=KoDetailOut, dependencies=[KoEditor])
async def check_conflicts(ko_id: str, service: KoServiceDep) -> KoDetailOut:
    return await service.check_conflicts(ko_id)


@router.get("/kos/{ko_id}/versions", response_model=list[KoVersionOut])
async def ko_versions(ko_id: str, service: KoServiceDep) -> list[KoVersionOut]:
    return await service.versions(ko_id)


@router.get("/kos/{ko_id}/versions/{version}", response_model=KoVersionOut)
async def ko_version(
    ko_id: str, version: Annotated[int, Path(ge=1)], service: KoServiceDep
) -> KoVersionOut:
    return await service.version(ko_id, version)


@router.get("/kos/{ko_id}/acl", response_model=DocumentAclOut)
async def get_ko_acl(ko_id: str, service: KoServiceDep) -> DocumentAclOut:
    return await service.get_acl(ko_id)


@router.put("/kos/{ko_id}/acl", response_model=DocumentAclOut, dependencies=[KoEditor])
async def set_ko_acl(ko_id: str, data: DocumentAclUpdate, service: KoServiceDep) -> DocumentAclOut:
    return await service.set_acl(ko_id, data)


@router.post(
    "/documents/{document_id}/faq",
    response_model=list[KoOut],
    status_code=201,
    dependencies=[KoEditor],
)
async def generate_faq(document_id: str, data: FaqGenerateIn, service: KoServiceDep) -> list[KoOut]:
    return await service.faq_from_document(document_id, data)


@router.get("/review-tasks", response_model=Page[ReviewTaskOut])
async def list_review_tasks(
    service: KoServiceDep,
    status: ReviewStatus | None = ReviewStatus.PENDING,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[ReviewTaskOut]:
    return await service.review_tasks(status=status.value if status else None, page=page, size=size)
