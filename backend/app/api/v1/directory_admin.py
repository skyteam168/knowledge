from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile

from app.api.deps import (
    AuthzCacheDep,
    DbSessionDep,
    RequestContextDep,
    ResourcesDep,
    SettingsDep,
    require_permission,
)
from app.core.exceptions import ValidationAppError
from app.schemas.common import Page
from app.schemas.directory import (
    DirectorySourceCreate,
    DirectorySourceOut,
    DirectorySourceUpdate,
    DirectoryTestRequest,
    DirectoryTestResult,
    SyncRequest,
    SyncRunDetail,
    SyncRunOut,
)
from app.services.directory.connectors.excel import build_template
from app.services.directory.service import DirectorySourceService

router = APIRouter(
    prefix="/admin/directory",
    tags=["directory-admin"],
    dependencies=[Depends(require_permission("admin:directory"))],
)
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def get_service(
    session: DbSessionDep,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> DirectorySourceService:
    return DirectorySourceService(
        session, ctx, cache, settings=settings, queue=resources.task_queue, cache=resources.cache
    )


ServiceDep = Annotated[DirectorySourceService, Depends(get_service)]


async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValidationAppError("File too large (max 20 MB)")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise ValidationAppError("Please upload an .xlsx file")
    return content


@router.get("/sources", response_model=list[DirectorySourceOut])
async def list_sources(service: ServiceDep) -> list[DirectorySourceOut]:
    return await service.list_sources()


@router.post("/sources", response_model=DirectorySourceOut, status_code=201)
async def create_source(data: DirectorySourceCreate, service: ServiceDep) -> DirectorySourceOut:
    return await service.create(data)


@router.put("/sources/{source_id}", response_model=DirectorySourceOut)
async def update_source(
    source_id: str, data: DirectorySourceUpdate, service: ServiceDep
) -> DirectorySourceOut:
    return await service.update(source_id, data)


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: str, service: ServiceDep) -> Response:
    await service.delete(source_id)
    return Response(status_code=204)


@router.post("/test", response_model=DirectoryTestResult)
async def test_connection(data: DirectoryTestRequest, service: ServiceDep) -> DirectoryTestResult:
    return await service.test(data)


@router.post("/sources/{source_id}/sync", response_model=SyncRunOut, status_code=202)
async def start_sync(source_id: str, data: SyncRequest, service: ServiceDep) -> SyncRunOut:
    return SyncRunOut.model_validate(await service.start(source_id, data.mode, data.force))


@router.post("/sources/{source_id}/upload", response_model=SyncRunDetail)
async def upload_sync(
    source_id: str,
    service: ServiceDep,
    file: Annotated[UploadFile, File()],
    mode: Annotated[Literal["preview", "apply"], Form()] = "preview",
    force: Annotated[bool, Form()] = False,
) -> SyncRunDetail:
    run = await service.run_upload(source_id, mode, force, await _read_upload(file))
    return SyncRunDetail.model_validate(run)


@router.get("/runs", response_model=Page[SyncRunOut])
async def list_runs(
    service: ServiceDep,
    source_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[SyncRunOut]:
    return await service.runs(source_id, page, size)


@router.get("/runs/{run_id}", response_model=SyncRunDetail)
async def get_run(run_id: str, service: ServiceDep) -> SyncRunDetail:
    return await service.run_detail(run_id)


@router.get("/excel-template")
async def excel_template() -> Response:
    return Response(
        content=build_template(),
        media_type=XLSX,
        headers={"Content-Disposition": "attachment; filename=directory-template.xlsx"},
    )
