from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response

from app.api.deps import get_document_service, require_permission
from app.schemas.knowledge import (
    ChunkOut,
    DocumentAclOut,
    DocumentAclUpdate,
    DocumentContentOut,
    DocumentContentUpdate,
    DocumentDetail,
    DocumentOut,
    DocumentReviewIn,
    DocumentUpdate,
    PreviewOut,
    UploadResult,
    VersionCompareOut,
    VersionTextOut,
)
from app.services.knowledge.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])
ServiceDep = Annotated[DocumentService, Depends(get_document_service)]
CanRead = [Depends(require_permission("kb:read"))]
CanUpload = [Depends(require_permission("doc:upload"))]


@router.get("/{document_id}", response_model=DocumentDetail, dependencies=CanRead)
async def get_document(document_id: str, service: ServiceDep) -> DocumentDetail:
    return await service.get(document_id)


@router.put("/{document_id}", response_model=DocumentOut, dependencies=CanUpload)
async def update_document(
    document_id: str, data: DocumentUpdate, service: ServiceDep
) -> DocumentOut:
    return await service.update(document_id, data)


@router.delete(
    "/{document_id}", status_code=204, dependencies=[Depends(require_permission("doc:delete"))]
)
async def delete_document(document_id: str, service: ServiceDep) -> Response:
    await service.delete(document_id)
    return Response(status_code=204)


@router.get("/{document_id}/content", response_model=DocumentContentOut, dependencies=CanUpload)
async def document_content(document_id: str, service: ServiceDep) -> DocumentContentOut:
    return await service.content(document_id)


@router.put("/{document_id}/content", response_model=UploadResult, dependencies=CanUpload)
async def save_document_content(
    document_id: str, data: DocumentContentUpdate, service: ServiceDep
) -> UploadResult:
    return await service.save_content(document_id, data)


@router.post("/{document_id}/review", response_model=DocumentOut, dependencies=CanUpload)
async def review_document(
    document_id: str, data: DocumentReviewIn, service: ServiceDep
) -> DocumentOut:
    return await service.review(document_id, data)


@router.post("/{document_id}/reprocess", response_model=DocumentOut, dependencies=CanUpload)
async def reprocess_document(document_id: str, service: ServiceDep) -> DocumentOut:
    return await service.reprocess(document_id)


@router.get("/{document_id}/chunks", response_model=list[ChunkOut], dependencies=CanRead)
async def list_chunks(document_id: str, service: ServiceDep) -> list[ChunkOut]:
    return await service.chunks(document_id)


@router.get("/{document_id}/preview-url", response_model=PreviewOut, dependencies=CanRead)
async def preview_url(document_id: str, service: ServiceDep) -> PreviewOut:
    return await service.preview_url(document_id)


@router.get("/{document_id}/download-url", response_model=PreviewOut, dependencies=CanRead)
async def download_url(document_id: str, service: ServiceDep) -> PreviewOut:
    return await service.download_url(document_id)


VersionNo = Annotated[int, Path(ge=1)]


@router.get(
    "/{document_id}/versions/compare", response_model=VersionCompareOut, dependencies=CanRead
)
async def compare_versions(
    document_id: str,
    service: ServiceDep,
    base: Annotated[int, Query(ge=1)],
    target: Annotated[int, Query(ge=1)],
) -> VersionCompareOut:
    return await service.compare_versions(document_id, base, target)


@router.get(
    "/{document_id}/versions/{version}/preview-url",
    response_model=PreviewOut,
    dependencies=CanRead,
)
async def version_preview_url(
    document_id: str, version: VersionNo, service: ServiceDep
) -> PreviewOut:
    return await service.preview_url(document_id, version)


@router.get(
    "/{document_id}/versions/{version}/download-url",
    response_model=PreviewOut,
    dependencies=CanRead,
)
async def version_download_url(
    document_id: str, version: VersionNo, service: ServiceDep
) -> PreviewOut:
    return await service.download_url(document_id, version)


@router.get(
    "/{document_id}/versions/{version}/text", response_model=VersionTextOut, dependencies=CanRead
)
async def version_text(document_id: str, version: VersionNo, service: ServiceDep) -> VersionTextOut:
    return await service.version_text(document_id, version)


@router.post(
    "/{document_id}/versions/{version}/restore",
    response_model=DocumentOut,
    dependencies=CanUpload,
)
async def restore_version(document_id: str, version: VersionNo, service: ServiceDep) -> DocumentOut:
    return await service.restore_version(document_id, version)


@router.get(
    "/{document_id}/pages/{page_index}/preview-url",
    response_model=PreviewOut,
    dependencies=CanRead,
)
async def page_preview_url(
    document_id: str,
    page_index: int,
    service: ServiceDep,
    kind: Annotated[Literal["page", "slide"], Query()] = "page",
) -> PreviewOut:
    return await service.page_asset_url(document_id, kind=kind, page_index=page_index)


@router.get("/{document_id}/acl", response_model=DocumentAclOut, dependencies=CanRead)
async def get_document_acl(document_id: str, service: ServiceDep) -> DocumentAclOut:
    return await service.get_acl(document_id)


@router.put("/{document_id}/acl", response_model=DocumentAclOut, dependencies=CanRead)
async def set_document_acl(
    document_id: str, data: DocumentAclUpdate, service: ServiceDep
) -> DocumentAclOut:
    return await service.set_acl(document_id, data)
