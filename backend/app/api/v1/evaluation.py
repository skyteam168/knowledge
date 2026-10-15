from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import (
    AuthzCacheDep,
    DbSessionDep,
    RequestContextDep,
    ResourcesDep,
    SettingsDep,
    require_permission,
)
from app.schemas.common import Page
from app.schemas.evaluation import (
    EvalCandidateOut,
    EvalCaseCreate,
    EvalCaseOut,
    EvalCaseUpdate,
    EvalCompareOut,
    EvalDatasetCreate,
    EvalDatasetOut,
    EvalDatasetUpdate,
    EvalImportIn,
    EvalImportOut,
    EvalResultOut,
    EvalRunCreate,
    EvalRunOut,
    ImportSource,
)
from app.services.evaluation.eval_service import EvalService

router = APIRouter(
    prefix="/evaluation",
    tags=["evaluation"],
    dependencies=[Depends(require_permission("admin:retrieval"))],
)


def get_service(
    session: DbSessionDep,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> EvalService:
    return EvalService(session, ctx, cache, settings=settings, queue=resources.task_queue)


ServiceDep = Annotated[EvalService, Depends(get_service)]
PageQuery = Annotated[int, Query(ge=1)]
SizeQuery = Annotated[int, Query(ge=1, le=100)]


# ---- datasets ---------------------------------------------------------------------------


@router.get("/datasets", response_model=Page[EvalDatasetOut])
async def list_datasets(
    service: ServiceDep, page: PageQuery = 1, size: SizeQuery = 20
) -> Page[EvalDatasetOut]:
    return await service.list_datasets(page, size)


@router.post("/datasets", response_model=EvalDatasetOut, status_code=201)
async def create_dataset(data: EvalDatasetCreate, service: ServiceDep) -> EvalDatasetOut:
    return await service.create_dataset(data)


@router.get("/datasets/{dataset_id}", response_model=EvalDatasetOut)
async def get_dataset(dataset_id: str, service: ServiceDep) -> EvalDatasetOut:
    return await service.get_dataset(dataset_id)


@router.patch("/datasets/{dataset_id}", response_model=EvalDatasetOut)
async def update_dataset(
    dataset_id: str, data: EvalDatasetUpdate, service: ServiceDep
) -> EvalDatasetOut:
    return await service.update_dataset(dataset_id, data)


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: str, service: ServiceDep) -> Response:
    await service.delete_dataset(dataset_id)
    return Response(status_code=204)


# ---- cases ------------------------------------------------------------------------------


@router.get("/datasets/{dataset_id}/cases", response_model=Page[EvalCaseOut])
async def list_cases(
    dataset_id: str,
    service: ServiceDep,
    page: PageQuery = 1,
    size: SizeQuery = 20,
    keyword: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[EvalCaseOut]:
    return await service.list_cases(dataset_id, page, size, keyword)


@router.post("/datasets/{dataset_id}/cases", response_model=EvalCaseOut, status_code=201)
async def create_case(dataset_id: str, data: EvalCaseCreate, service: ServiceDep) -> EvalCaseOut:
    return await service.create_case(dataset_id, data)


@router.patch("/cases/{case_id}", response_model=EvalCaseOut)
async def update_case(case_id: str, data: EvalCaseUpdate, service: ServiceDep) -> EvalCaseOut:
    return await service.update_case(case_id, data)


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(case_id: str, service: ServiceDep) -> Response:
    await service.delete_case(case_id)
    return Response(status_code=204)


@router.get("/candidates", response_model=Page[EvalCandidateOut])
async def candidates(
    service: ServiceDep,
    source: ImportSource,
    dataset_id: Annotated[str | None, Query(description="Marks already imported items")] = None,
    keyword: Annotated[str | None, Query(max_length=200)] = None,
    page: PageQuery = 1,
    size: SizeQuery = 20,
) -> Page[EvalCandidateOut]:
    """Upvoted answers (`feedback`) or resolved gaps (`gap`) that can become cases."""
    return await service.candidates(source, page, size, dataset_id, keyword)


@router.post("/datasets/{dataset_id}/import", response_model=EvalImportOut)
async def import_cases(dataset_id: str, data: EvalImportIn, service: ServiceDep) -> EvalImportOut:
    return await service.import_cases(dataset_id, data)


# ---- runs -------------------------------------------------------------------------------


@router.get("/runs", response_model=Page[EvalRunOut])
async def list_runs(
    service: ServiceDep,
    dataset_id: str | None = None,
    page: PageQuery = 1,
    size: SizeQuery = 20,
) -> Page[EvalRunOut]:
    return await service.list_runs(page, size, dataset_id)


@router.post("/runs", response_model=EvalRunOut, status_code=201)
async def create_run(data: EvalRunCreate, service: ServiceDep) -> EvalRunOut:
    return await service.create_run(data)


@router.get("/runs/compare", response_model=EvalCompareOut)
async def compare_runs(
    service: ServiceDep, run_ids: Annotated[list[str], Query(min_length=2, max_length=4)]
) -> EvalCompareOut:
    return await service.compare(run_ids)


@router.get("/runs/{run_id}", response_model=EvalRunOut)
async def get_run(run_id: str, service: ServiceDep) -> EvalRunOut:
    return await service.get_run(run_id)


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: str, service: ServiceDep) -> Response:
    await service.delete_run(run_id)
    return Response(status_code=204)


@router.get("/runs/{run_id}/results", response_model=Page[EvalResultOut])
async def run_results(
    run_id: str,
    service: ServiceDep,
    only_failed: bool = False,
    page: PageQuery = 1,
    size: SizeQuery = 20,
) -> Page[EvalResultOut]:
    return await service.run_results(run_id, page, size, only_failed)
