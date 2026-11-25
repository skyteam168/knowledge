"""Admin APIs for ontology rules and action types."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuthzCacheDep, DbSessionDep, RequestContextDep, require_permission
from app.schemas.ontology_governance import (
    ActionTypeCreate,
    ActionTypeOut,
    ActionTypeUpdate,
    OntologyRuleCreate,
    OntologyRuleOut,
    OntologyRuleUpdate,
)
from app.services.ontology_studio.governance import OntologyGovernanceService

router = APIRouter(
    prefix="/admin/ontology",
    tags=["admin:ontology-governance"],
    dependencies=[Depends(require_permission("admin:retrieval"))],
)


def get_service(
    session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep
) -> OntologyGovernanceService:
    return OntologyGovernanceService(session, ctx, cache)


ServiceDep = Annotated[OntologyGovernanceService, Depends(get_service)]


@router.get("/rules", response_model=list[OntologyRuleOut])
async def list_rules(service: ServiceDep) -> list[OntologyRuleOut]:
    return await service.list_rules()


@router.post("/rules", response_model=OntologyRuleOut, status_code=201)
async def create_rule(data: OntologyRuleCreate, service: ServiceDep) -> OntologyRuleOut:
    return await service.create_rule(data)


@router.patch("/rules/{rule_id}", response_model=OntologyRuleOut)
async def patch_rule(
    rule_id: str, data: OntologyRuleUpdate, service: ServiceDep
) -> OntologyRuleOut:
    return await service.patch_rule(rule_id, data)


@router.get("/action-types", response_model=list[ActionTypeOut])
async def list_action_types(
    service: ServiceDep,
    enabled_only: bool = Query(default=False),
) -> list[ActionTypeOut]:
    return await service.list_action_types(enabled_only=enabled_only)


@router.post("/action-types", response_model=ActionTypeOut, status_code=201)
async def create_action_type(
    data: ActionTypeCreate, service: ServiceDep
) -> ActionTypeOut:
    return await service.create_action_type(data)


@router.patch("/action-types/{action_id}", response_model=ActionTypeOut)
async def patch_action_type(
    action_id: str, data: ActionTypeUpdate, service: ServiceDep
) -> ActionTypeOut:
    return await service.patch_action_type(action_id, data)
