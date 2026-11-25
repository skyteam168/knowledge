"""Admin APIs for canonical entities / identifiers."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import AuthzCacheDep, DbSessionDep, RequestContextDep, require_permission
from app.schemas.common import Page
from app.schemas.identity_admin import (
    CanonicalCreate,
    CanonicalOut,
    IdentifierCreate,
    IdentifierOut,
    ResolveMatchIn,
    ResolveMatchOut,
)
from app.services.structured.identity_admin import IdentityAdminService

router = APIRouter(
    prefix="/admin/structured/identity",
    tags=["admin:identity"],
    dependencies=[Depends(require_permission("admin:retrieval"))],
)


def get_service(
    session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep
) -> IdentityAdminService:
    return IdentityAdminService(session, ctx, cache)


ServiceDep = Annotated[IdentityAdminService, Depends(get_service)]


@router.get("/canonical", response_model=Page[CanonicalOut])
async def list_canonical(
    service: ServiceDep,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    object_type: str | None = None,
    status: str | None = None,
    q: str | None = None,
) -> Page[CanonicalOut]:
    return await service.list_canonical(
        page=page, size=size, object_type=object_type, status=status, q=q
    )


@router.post("/canonical", response_model=CanonicalOut, status_code=201)
async def create_canonical(data: CanonicalCreate, service: ServiceDep) -> CanonicalOut:
    return await service.create_canonical(data)


@router.get("/canonical/{canonical_id}", response_model=CanonicalOut)
async def get_canonical(canonical_id: str, service: ServiceDep) -> CanonicalOut:
    return await service.get_canonical(canonical_id)


@router.post(
    "/canonical/{canonical_id}/identifiers",
    response_model=IdentifierOut,
    status_code=201,
)
async def add_identifier(
    canonical_id: str, data: IdentifierCreate, service: ServiceDep
) -> IdentifierOut:
    return await service.add_identifier(canonical_id, data)


@router.delete("/identifiers/{identifier_id}", status_code=204)
async def delete_identifier(identifier_id: str, service: ServiceDep) -> Response:
    await service.delete_identifier(identifier_id)
    return Response(status_code=204)


@router.get("/conflicts", response_model=Page[CanonicalOut])
async def list_conflicts(
    service: ServiceDep,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> Page[CanonicalOut]:
    return await service.list_conflicts(page=page, size=size)


@router.post("/resolve-match", response_model=ResolveMatchOut)
async def resolve_match(data: ResolveMatchIn, service: ServiceDep) -> ResolveMatchOut:
    return await service.resolve_match(data)
