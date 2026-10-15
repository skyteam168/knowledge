from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile

from app.api.deps import get_document_service, provide, require_permission
from app.models import DocumentStatus
from app.schemas.common import Page
from app.schemas.knowledge import (
    DocumentOut,
    KbAclOut,
    KbAclUpdate,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    UploadComplete,
    UploadInit,
    UploadInitOut,
    UploadResult,
)
from app.services.knowledge.document_service import DocumentService
from app.services.knowledge.kb_service import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])
KbServiceDep = Annotated[KnowledgeBaseService, Depends(provide(KnowledgeBaseService))]
DocServiceDep = Annotated[DocumentService, Depends(get_document_service)]
CanRead = [Depends(require_permission("kb:read"))]
CanUpload = [Depends(require_permission("doc:upload"))]


@router.get("", response_model=Page[KnowledgeBaseOut], dependencies=CanRead)
async def list_knowledge_bases(
    service: KbServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    keyword: str | None = None,
) -> Page[KnowledgeBaseOut]:
    return await service.search(page=page, size=size, keyword=keyword)


@router.post(
    "",
    response_model=KnowledgeBaseOut,
    status_code=201,
    dependencies=[Depends(require_permission("kb:create"))],
)
async def create_knowledge_base(
    data: KnowledgeBaseCreate, service: KbServiceDep
) -> KnowledgeBaseOut:
    return await service.create(data)


@router.get("/{kb_id}", response_model=KnowledgeBaseOut, dependencies=CanRead)
async def get_knowledge_base(kb_id: str, service: KbServiceDep) -> KnowledgeBaseOut:
    return await service.get(kb_id)


@router.put(
    "/{kb_id}",
    response_model=KnowledgeBaseOut,
    dependencies=[Depends(require_permission("kb:update"))],
)
async def update_knowledge_base(
    kb_id: str, data: KnowledgeBaseUpdate, service: KbServiceDep
) -> KnowledgeBaseOut:
    return await service.update(kb_id, data)


@router.delete("/{kb_id}", status_code=204, dependencies=[Depends(require_permission("kb:delete"))])
async def delete_knowledge_base(kb_id: str, service: KbServiceDep) -> Response:
    await service.delete(kb_id)
    return Response(status_code=204)


@router.get(
    "/{kb_id}/acl", response_model=KbAclOut, dependencies=[Depends(require_permission("kb:update"))]
)
async def get_knowledge_base_acl(kb_id: str, service: KbServiceDep) -> KbAclOut:
    return await service.get_acl(kb_id)


@router.put(
    "/{kb_id}/acl", response_model=KbAclOut, dependencies=[Depends(require_permission("kb:update"))]
)
async def set_knowledge_base_acl(kb_id: str, data: KbAclUpdate, service: KbServiceDep) -> KbAclOut:
    return await service.set_acl(kb_id, data)


@router.get("/{kb_id}/documents", response_model=Page[DocumentOut], dependencies=CanRead)
async def list_documents(
    kb_id: str,
    service: DocServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    status: DocumentStatus | None = None,
    keyword: str | None = None,
) -> Page[DocumentOut]:
    return await service.search(
        kb_id, page=page, size=size, status=status.value if status else None, keyword=keyword
    )


@router.post("/{kb_id}/documents/upload-url", response_model=UploadInitOut, dependencies=CanUpload)
async def create_upload(kb_id: str, data: UploadInit, service: DocServiceDep) -> UploadInitOut:
    return await service.create_upload(kb_id, data)


@router.post("/{kb_id}/documents/complete", response_model=UploadResult, dependencies=CanUpload)
async def complete_upload(kb_id: str, data: UploadComplete, service: DocServiceDep) -> UploadResult:
    return await service.complete_upload(kb_id, data)


@router.post("/{kb_id}/documents", response_model=UploadResult, dependencies=CanUpload)
async def upload_document(
    kb_id: str,
    service: DocServiceDep,
    file: Annotated[UploadFile, File()],
    tags: Annotated[list[str] | None, Form()] = None,
) -> UploadResult:
    content = await file.read()
    return await service.upload_direct(
        kb_id,
        filename=file.filename or "unnamed",
        content=content,
        mime_type=file.content_type,
        tags=tags,
    )
