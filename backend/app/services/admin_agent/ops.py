"""Platform operations of the admin assistant: audit log, models, evaluation, open platform and
index status (read), plus starting an offline evaluation (write, queued after commit).

Every lookup goes through the regular admin services, so their permission checks apply. Results
never carry secrets (API keys, provider keys).
"""

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import func, select

from app.core.exceptions import AppError
from app.models import ApiClient, AuditLog, EvalCase, EvalDataset, EvalRun
from app.repositories.audit_repo import AuditQuery
from app.repositories.indexing_repo import IndexGenerationRepository, OutboxRepository
from app.schemas.evaluation import EvalRunCreate
from app.schemas.indexing import OutboxStatsOut
from app.services.admin_agent.resolve import Planned, ResolveError, similar_names
from app.services.admin_agent.tools import (
    TOOLS,
    AgentContext,
    Args,
    NoArgs,
    StepPreview,
    Tool,
)
from app.services.audit_service import AuditService
from app.services.evaluation.eval_service import ACTIVE_RUN, EvalService
from app.services.knowledge.directory import PrincipalDirectory
from app.services.models.service import ModelAdminService
from app.services.open_api.client_service import OpenApiClientService
from app.services.search.profile_service import BUILTIN_NAME, RetrievalProfileService

MAX_AUDIT_ROWS = 100
DEFAULT_AUDIT_DAYS = 7
MAX_CHANGES = 4
VALUE_CHARS = 60

AuditTarget = Literal["user", "group", "role", "department", "knowledge_base", "api_client"]
AUDIT_RESOURCE = {
    "user": "user",
    "group": "group",
    "role": "role",
    "department": "department",
    "knowledge_base": "kb",
    "api_client": "api_client",
}
# audit resource type -> ACL principal type (for naming)
PRINCIPAL_OF = {"user": "user", "group": "group", "role": "role", "department": "dept"}


# ---- audit log ---------------------------------------------------------------------------


class AuditArgs(Args):
    actor: str | None = Field(None, description="操作人账号 / 工号 / 姓名")
    action: str | None = Field(
        None,
        description="操作类别前缀：user / group / role / department / kb / kb.set_acl / "
        "document / ko / openapi / eval / admin_agent / directory / index / retrieval_profile",
    )
    target_type: AuditTarget | None = None
    target: str | None = Field(None, description="被操作对象的名称")
    start: date | None = Field(None, description="开始日期 YYYY-MM-DD（含）")
    end: date | None = Field(None, description="结束日期 YYYY-MM-DD（含）")
    limit: int = Field(30, ge=1, le=MAX_AUDIT_ROWS)


async def _target_id(a: AgentContext, ttype: str, key: str) -> str:
    r = a.resolver
    if ttype == "user":
        return (await r.user(key, include_inactive=True)).id
    if ttype == "group":
        return (await r.group(key)).id
    if ttype == "role":
        return (await r.role(key)).id
    if ttype == "department":
        return (await r.department(key))[0].id
    if ttype == "knowledge_base":
        return (await r.knowledge_base(key)).id
    client = (
        await a.session.execute(
            select(ApiClient).where(ApiClient.org_id == a.ctx.org_id, ApiClient.name == key.strip())
        )
    ).scalar_one_or_none()
    if client is None:
        raise ResolveError("target_not_found", key)
    return client.id


async def _audit_target(a: AgentContext, args: AuditArgs) -> tuple[str | None, str | None]:
    if not args.target:
        return (AUDIT_RESOURCE[args.target_type] if args.target_type else None), None
    if args.target_type:
        return AUDIT_RESOURCE[args.target_type], await _target_id(a, args.target_type, args.target)
    for ttype in ("knowledge_base", "group", "role", "department", "user", "api_client"):
        try:
            return AUDIT_RESOURCE[ttype], await _target_id(a, ttype, args.target)
        except ResolveError:
            continue
    raise ResolveError("target_not_found", args.target)


def _range(a: AgentContext, args: AuditArgs) -> tuple[date, date, ZoneInfo]:
    tz = ZoneInfo(a.settings.analytics_timezone)
    today = datetime.now(tz).date()
    end = args.end or (args.start + timedelta(days=DEFAULT_AUDIT_DAYS - 1) if args.start else today)
    start = args.start or end - timedelta(days=DEFAULT_AUDIT_DAYS - 1)
    return min(start, end), max(start, end), tz


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= VALUE_CHARS else text[: VALUE_CHARS - 1] + "…"


def _acl_entries(snapshot: dict[str, Any] | None) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for item in (snapshot or {}).get("entries") or []:
        parts = str(item).split(":")
        if len(parts) == 3:
            out[(parts[0], parts[1])] = parts[2]
    return out


async def _changes(a: AgentContext, log: AuditLog) -> list[str]:
    if log.action.endswith("set_acl"):
        before, after = _acl_entries(log.before), _acl_entries(log.after)
        names = await PrincipalDirectory(a.session, a.ctx.org_id).names(set(before) | set(after))
        lines = []
        for key in sorted(set(before) | set(after)):
            who = f"{key[0]}:{names.get(key) or f'<deleted {key[1][:6]}>'}"
            if key not in before:
                lines.append(f"+ {who} → {after[key]}")
            elif key not in after:
                lines.append(f"- {who} ({before[key]})")
            elif before[key] != after[key]:
                lines.append(f"{who}: {before[key]} → {after[key]}")
        vis_before = (log.before or {}).get("visibility")
        vis_after = (log.after or {}).get("visibility")
        if vis_before != vis_after:
            lines.append(f"visibility: {vis_before} → {vis_after}")
        return lines[: MAX_CHANGES * 2]
    return [
        f"{key}: {_short(change.get('before'))} → {_short(change.get('after'))}"
        for key, change in list((log.diff or {}).items())[:MAX_CHANGES]
    ]


def _snapshot_name(log: AuditLog) -> str | None:
    for snap in (log.after, log.before):
        for key in ("name", "username", "title", "message"):
            if snap and snap.get(key):
                return _short(snap[key])
    return None


async def _resource_names(a: AgentContext, logs: list[AuditLog]) -> dict[tuple[str, str], str]:
    pairs = {
        (log.resource_type, log.resource_id)
        for log in logs
        if log.resource_type and log.resource_id
    }
    names: dict[tuple[str, str], str] = {}
    directory = await PrincipalDirectory(a.session, a.ctx.org_id).names(
        (PRINCIPAL_OF[t], i) for t, i in pairs if t in PRINCIPAL_OF
    )
    for (ptype, pid), name in directory.items():
        rtype = next(t for t, p in PRINCIPAL_OF.items() if p == ptype)
        names[(rtype, pid)] = name
    kb_ids = [i for t, i in pairs if t == "kb"]
    for kb_id in kb_ids:
        try:
            names[("kb", kb_id)] = (await a.resolver.knowledge_base(kb_id)).name
        except ResolveError:
            continue
    return names


async def search_audit(a: AgentContext, args: AuditArgs) -> dict[str, Any]:
    actor_id = (await a.resolver.user(args.actor, include_inactive=True)).id if args.actor else None
    resource_type, resource_id = await _audit_target(a, args)
    start, end, tz = _range(a, args)
    query = AuditQuery(
        actor_id,
        args.action,
        resource_type,
        resource_id,
        None,
        datetime.combine(start, time.min, tzinfo=tz).astimezone(UTC),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC),
    )
    logs, total = await AuditService(a.session).search(a.ctx.org_id, query, 1, args.limit)
    names = await _resource_names(a, logs)
    items = []
    for log in logs:
        key = (log.resource_type or "", log.resource_id or "")
        items.append(
            {
                "time": log.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                "actor": log.actor_name or "system",
                "action": log.action,
                "target": names.get(key) or _snapshot_name(log) or log.resource_id or "-",
                "changes": await _changes(a, log),
            }
        )
    return {"range": f"{start} ~ {end}", "total": total, "shown": len(items), "items": items}


# ---- models / open platform / index --------------------------------------------------------


async def model_status(a: AgentContext, _: NoArgs) -> dict[str, Any]:
    svc = ModelAdminService(a.session, a.ctx, a.authz_cache, settings=a.settings, router=None)
    overview = await svc.overview()
    page = await svc.list_models(None, None, None, 1, 200)
    relevant = [m for m in page.items if m.scenes or m.last_check_status]
    return {
        "scenes": [
            {
                "scene": s.scene,
                "kind": s.kind,
                "model": s.model,
                "provider": s.provider_name,
                "source": s.source,
            }
            for s in overview.scenes
        ],
        "models": [
            {
                "name": m.name,
                "kind": m.kind,
                "provider": m.provider_name,
                "scenes": m.scenes,
                "status": m.last_check_status,
                "latency_ms": m.last_check_latency_ms,
                "checked_at": m.last_check_at,
            }
            for m in relevant
        ],
        "other_models": page.total - len(relevant),
    }


class ClientArgs(Args):
    keyword: str | None = Field(None, description="应用名称关键词")


async def list_api_clients(a: AgentContext, args: ClientArgs) -> list[dict[str, Any]]:
    svc = OpenApiClientService(a.session, a.ctx, a.authz_cache, settings=a.settings)
    page = await svc.list_clients(page=1, size=50, keyword=args.keyword, status=None)
    return [
        {
            "name": c.name,
            "status": c.status,
            "knowledge_bases": [k.name for k in c.kbs],
            "scopes": c.scopes,
            "rate_per_minute": c.effective_rate_per_minute,
            "daily_quota": c.daily_quota,
            "active_keys": c.active_keys,
            "calls_today": c.calls_today,
            "last_used_at": c.last_used_at,
            "expires_at": c.expires_at,
        }
        for c in page.items
    ]


async def index_status(a: AgentContext, _: NoArgs) -> dict[str, Any]:
    outbox = OutboxStatsOut(**await OutboxRepository(a.session).status_counts(a.ctx.org_id))
    generations = await IndexGenerationRepository(a.session).all()
    return {
        "outbox": outbox.model_dump(),
        "generations": [
            {
                "version": g.version,
                "status": g.status,
                "embedding_model": g.embedding_model,
                "embedding_dim": g.embedding_dim,
                "created_at": g.created_at,
                "activated_at": g.activated_at,
                "error": g.error,
            }
            for g in generations
        ],
    }


# ---- evaluation ----------------------------------------------------------------------------


def _eval(a: AgentContext) -> EvalService:
    if a.queue is None:
        raise AppError("评测任务队列不可用", code="AGENT_QUEUE_UNAVAILABLE")
    return EvalService(a.session, a.ctx, a.authz_cache, settings=a.settings, queue=a.queue)


async def _dataset(a: AgentContext, key: str) -> EvalDataset:
    rows = list(
        (
            await a.session.execute(select(EvalDataset).where(EvalDataset.org_id == a.ctx.org_id))
        ).scalars()
    )
    hit = next((d for d in rows if key.strip() in (d.id, d.name)), None)
    if hit is None:
        raise ResolveError("dataset_not_found", key, similar_names(key, [d.name for d in rows]))
    return hit


async def list_eval_datasets(a: AgentContext, _: NoArgs) -> list[dict[str, Any]]:
    page = await _eval(a).list_datasets(1, 50)
    return [
        {"name": d.name, "cases": d.case_count, "description": d.description} for d in page.items
    ]


class EvalRunsArgs(Args):
    dataset: str | None = Field(None, description="评测集名称；留空为全部")
    limit: int = Field(5, ge=1, le=20)


def _metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()}


async def list_eval_runs(a: AgentContext, args: EvalRunsArgs) -> list[dict[str, Any]]:
    dataset_id = (await _dataset(a, args.dataset)).id if args.dataset else None
    page = await _eval(a).list_runs(1, args.limit, dataset_id)
    return [
        {
            "name": r.name or r.id[:8],
            "dataset": r.dataset_name,
            "profile": r.profile_name,
            "status": r.status,
            "progress": f"{r.done_count}/{r.case_count}",
            "judge": r.judge_enabled,
            "metrics": _metrics(r.metrics),
            "created_at": r.created_at,
            "error": r.error,
        }
        for r in page.items
    ]


class EvalCompareArgs(Args):
    dataset: str | None = Field(None, description="评测集名称；留空比较最近完成的两次")


async def compare_eval_runs(a: AgentContext, args: EvalCompareArgs) -> dict[str, Any]:
    stmt = select(EvalRun).where(EvalRun.org_id == a.ctx.org_id, EvalRun.status == "done")
    if args.dataset:
        stmt = stmt.where(EvalRun.dataset_id == (await _dataset(a, args.dataset)).id)
    runs = list(
        (await a.session.execute(stmt.order_by(EvalRun.created_at.desc()).limit(2))).scalars()
    )
    if len(runs) < 2:
        return {"error": "fewer than two finished runs"}
    out = await _eval(a).compare([r.id for r in reversed(runs)])
    return {
        "runs": [
            {"name": r.name or r.id[:8], "profile": r.profile_name, "created_at": r.created_at}
            for r in out.runs
        ],
        "metrics": {
            key: [_metrics(r.metrics).get(key) for r in out.runs] for key in out.metric_keys
        },
        "config_diff": [
            {"key": d.key, "values": [d.values.get(r.id) for r in out.runs]}
            for d in out.config_diff[:20]
        ],
    }


class StartEvalArgs(Args):
    dataset: str = Field(description="评测集名称")
    profile: str | None = Field(None, description="检索策略名称；留空用当前启用的策略")
    judge: bool = Field(True, description="是否生成答案并用模型打分（较慢、消耗模型调用）")
    name: str | None = Field(None, max_length=128)


async def _profile(a: AgentContext, key: str | None) -> tuple[str, str]:
    """(profile id or "builtin", name)."""
    svc = RetrievalProfileService(a.session, a.ctx, a.authz_cache, settings=a.settings)
    if key is None:
        resolved = await svc.resolve()
        return resolved.id or BUILTIN_NAME, resolved.name
    profiles = await svc.list()
    wanted = key.strip().lower()
    if wanted in (BUILTIN_NAME, "内置", "默认", "default"):
        return BUILTIN_NAME, BUILTIN_NAME
    hit = next((p for p in profiles if p.name.lower() == wanted), None)
    if hit is None:
        raise ResolveError("profile_not_found", key, [p.name for p in profiles][:10])
    return hit.id or BUILTIN_NAME, hit.name


async def preview_start_eval(a: AgentContext, args: StartEvalArgs, planned: Planned) -> StepPreview:
    ds = await _dataset(a, args.dataset)
    cases = int(
        await a.session.scalar(select(func.count()).where(EvalCase.dataset_id == ds.id)) or 0
    )
    if cases == 0:
        raise ResolveError("dataset_empty", ds.name)
    _, profile_name = await _profile(a, args.profile)
    warnings: list[dict[str, str]] = []
    if args.judge and a.settings.eval_judge_enabled:
        warnings.append({"code": "judge_cost"})
    elif args.judge:
        warnings.append({"code": "judge_disabled"})
    running = await a.session.scalar(
        select(func.count()).where(EvalRun.dataset_id == ds.id, EvalRun.status.in_(ACTIVE_RUN))
    )
    if running:
        warnings.append({"code": "eval_running"})
    return StepPreview(
        {
            "dataset": ds.name,
            "profile": profile_name,
            "cases": str(min(cases, a.settings.eval_max_cases_per_run)),
        },
        warnings,
    )


async def run_start_eval(a: AgentContext, args: StartEvalArgs) -> dict[str, Any]:
    ds = await _dataset(a, args.dataset)
    profile_id, profile_name = await _profile(a, args.profile)
    run = await _eval(a).create_run(
        EvalRunCreate(
            dataset_id=ds.id, profile_id=profile_id, name=args.name, judge_enabled=args.judge
        )
    )
    return {"dataset": ds.name, "profile": profile_name, "run": run.name or run.id[:8]}


OPS_TOOLS = (
    Tool(
        "search_audit_logs",
        "read",
        "查询审计日志：谁在什么时间对什么做了什么修改。",
        AuditArgs,
        ("admin:audit",),
        search_audit,
    ),
    Tool(
        "model_status",
        "read",
        "查看对话 / 向量 / 重排各场景当前使用的模型，以及各模型最近一次检测结果。",
        NoArgs,
        ("admin:model",),
        model_status,
    ),
    Tool(
        "list_api_clients",
        "read",
        "列出开放平台应用：状态、授权知识库、权限范围、限流、今日调用量（不含密钥）。",
        ClientArgs,
        ("admin:openapi",),
        list_api_clients,
    ),
    Tool(
        "index_status",
        "read",
        "查看索引同步队列（待处理 / 处理中 / 已完成 / 死信）和索引代次。",
        NoArgs,
        ("admin:index",),
        index_status,
    ),
    Tool(
        "list_eval_datasets",
        "read",
        "列出评测集及用例数。",
        NoArgs,
        ("admin:retrieval",),
        list_eval_datasets,
    ),
    Tool(
        "list_eval_runs",
        "read",
        "列出最近的离线评测运行：策略、状态、进度、指标。",
        EvalRunsArgs,
        ("admin:retrieval",),
        list_eval_runs,
    ),
    Tool(
        "compare_eval_runs",
        "read",
        "对比最近两次已完成的离线评测：指标与配置差异。",
        EvalCompareArgs,
        ("admin:retrieval",),
        compare_eval_runs,
    ),
    Tool(
        "start_eval_run",
        "write",
        "对评测集发起一次离线评测（后台执行，完成后在离线评测页查看）。",
        StartEvalArgs,
        ("admin:retrieval",),
        run_start_eval,
        preview_start_eval,
    ),
)

TOOLS.update({t.name: t for t in OPS_TOOLS})
