"""Admin APIs for ontology rules and action types."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuthzCacheDep, DbSessionDep, RequestContextDep, require_permission
from app.schemas.ontology_governance import (
    ActionApproveIn,
    ActionApprovalOut,
    ActionExecutionListItem,
    ActionExecutionOut,
    ActionInvokeIn,
    ActionTypeCreate,
    ActionTypeOut,
    ActionTypeUpdate,
    OntologyRuleCreate,
    OntologyRuleOut,
    OntologyRuleUpdate,
)
from app.services.action.runtime import ActionRuntime
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


def get_runtime(session: DbSessionDep, ctx: RequestContextDep) -> ActionRuntime:
    return ActionRuntime(session, ctx)


ServiceDep = Annotated[OntologyGovernanceService, Depends(get_service)]
RuntimeDep = Annotated[ActionRuntime, Depends(get_runtime)]


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


@router.post("/actions/dry-run", response_model=ActionExecutionOut)
async def dry_run_action(data: ActionInvokeIn, runtime: RuntimeDep) -> ActionExecutionOut:
    result = await runtime.execute(
        data.action_type,
        dict(data.payload or {}),
        idempotency_key=data.idempotency_key,
        approval_id=data.approval_id,
        dry_run=True,
    )
    return ActionExecutionOut(
        id=result.execution_id,
        status=result.status,
        action_type=result.action_type,
        result=result.result,
        error=result.error,
        approval_id=result.approval_id,
        rule_verdict=result.rule_verdict,
    )


@router.post("/actions/approve", response_model=ActionApprovalOut, status_code=201)
async def approve_action(data: ActionApproveIn, runtime: RuntimeDep) -> ActionApprovalOut:
    row = await runtime.create_approval(
        data.action_type,
        dict(data.payload or {}),
        acknowledge_risk=data.acknowledge_risk,
    )
    return ActionApprovalOut(
        id=row.id,
        action_type=row.action_type,
        expires_at=row.expires_at,
        acknowledge_risk=row.acknowledge_risk,
    )


@router.post("/actions/invoke", response_model=ActionExecutionOut)
async def invoke_action(data: ActionInvokeIn, runtime: RuntimeDep) -> ActionExecutionOut:
    result = await runtime.execute(
        data.action_type,
        dict(data.payload or {}),
        idempotency_key=data.idempotency_key,
        approval_id=data.approval_id,
        dry_run=False,
    )
    return ActionExecutionOut(
        id=result.execution_id,
        status=result.status,
        action_type=result.action_type,
        result=result.result,
        error=result.error,
        approval_id=result.approval_id,
        rule_verdict=result.rule_verdict,
    )


@router.get("/actions/executions", response_model=list[ActionExecutionListItem])
async def list_action_executions(
    runtime: RuntimeDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActionExecutionListItem]:
    rows = await runtime.list_executions(limit=limit)
    return [
        ActionExecutionListItem(
            id=row.id,
            action_type=row.action_type,
            status=row.status,
            idempotency_key=row.idempotency_key,
            error=row.error,
            rule_verdict=(row.result or {}).get("rule_verdict")
            if isinstance(row.result, dict)
            else None,
            result=dict(row.result or {}),
            created_at=row.created_at,
            duration_ms=int(row.latency_ms) if row.latency_ms is not None else None,
        )
        for row in rows
    ]
