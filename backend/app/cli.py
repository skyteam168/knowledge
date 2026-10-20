"""Operations CLI: `python -m app.cli index <command>` / `python -m app.cli analytics refresh`.

bootstrap                      create the active generation, collection, index and aliases
generations                    list index generations
rebuild [--embedding-model M --embedding-dim N --embedding-base-url U] [--drop-old] [--strict]
                               full rebuild from PG into a new generation, then switch aliases
activate VERSION               point the aliases at an existing generation (rollback)
drop VERSION                   delete a non-active generation's collection and index
check --kb KB [--repair]       compare PG / Qdrant / OpenSearch for a knowledge base
reload-synonyms                reload the OpenSearch synonym dictionary (no reindex)

analytics refresh [--days N] [--org ORG_ID]
                               rebuild the daily analytics summaries of the last N days

keycloak setup-idp [--providers wecom dingtalk] [--admin-user U --admin-password P]
                               register the WeCom / DingTalk OIDC bridge as Keycloak identity
                               providers, the auto-link first-login flow, relaxed user profile
                               and the ekb-backend service account roles (idempotent)

agent eval [--lang zh|en|vi] [--limit N] [--no-tools] [--out report.json]
                               score the admin assistant's intent understanding (real model)
                               on the multilingual instruction set; prints accuracy per language

users fix-duplicates [--apply]
                               find users whose usernames differ only by case (e.g. pre-created
                               `Hien` + auto-created `hien`) and move the Keycloak identity onto
                               the pre-created one; dry run unless --apply

eval gold-check [--cases PATH] [--rankings PATH]
                               offline retrieval gold gate (same as pytest -m gold)
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.cache import RedisCache
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.core.logging import setup_logging
from app.llm import EmbeddingSpec, build_llm_gateway
from app.models import KnowledgeBase
from app.services.admin.duplicate_users import fix_case_duplicates
from app.services.admin_agent.evaluate import load_cases, run_case, summarize
from app.services.analytics.aggregator import AnalyticsAggregator
from app.services.authz.cache import AuthzCache
from app.services.indexing.consistency import ConsistencyReport
from app.services.indexing.generations import GenerationConflictError
from app.services.indexing.rebuild import RebuildVerificationError
from app.services.indexing.runtime import IndexingRuntime
from app.services.keycloak_admin import BRIDGE_PROVIDERS, KeycloakAdmin, identity_provider
from app.services.models.runtime import attach_chat_routing


def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _report_dict(report: ConsistencyReport) -> dict[str, Any]:
    data = asdict(report)
    data["consistent"] = report.consistent
    return data


async def _bootstrap(rt: IndexingRuntime, args: argparse.Namespace) -> int:
    target = await rt.registry.bootstrap()
    _print(asdict(target))
    return 0


async def _generations(rt: IndexingRuntime, args: argparse.Namespace) -> int:
    _print(
        [
            {
                "version": g.version,
                "status": g.status,
                "qdrant_collection": g.qdrant_collection,
                "opensearch_index": g.opensearch_index,
                "embedding_model": g.embedding_model,
                "embedding_dim": g.embedding_dim,
                "stats": g.stats,
                "created_at": g.created_at,
                "activated_at": g.activated_at,
            }
            for g in await rt.registry.generations()
        ]
    )
    return 0


async def _rebuild(rt: IndexingRuntime, args: argparse.Namespace) -> int:
    default = rt.gateway.default_embedding
    spec = EmbeddingSpec(
        model=args.embedding_model or default.model,
        dim=args.embedding_dim or default.dim,
        base_url=args.embedding_base_url or default.base_url,
    )

    def progress(documents: int, chunks: int) -> None:
        print(f"... {documents} documents, {chunks} chunks", file=sys.stderr)

    result = await rt.rebuilder.rebuild(
        spec,
        batch_size=args.batch_size,
        strict=args.strict,
        activate=not args.no_activate,
        drop_old=args.drop_old,
        progress=progress,
    )
    _print(asdict(result))
    return 0


async def _activate(rt: IndexingRuntime, args: argparse.Namespace) -> int:
    await rt.registry.activate(args.version)
    print(f"aliases now point at generation {args.version}")
    return 0


async def _drop(rt: IndexingRuntime, args: argparse.Namespace) -> int:
    await rt.registry.drop_physical(args.version)
    print(f"generation {args.version} dropped")
    return 0


async def _check(rt: IndexingRuntime, args: argparse.Namespace) -> int:
    async with rt.session_factory() as session:
        kb = await session.get(KnowledgeBase, args.kb)
    if kb is None:
        print(f"knowledge base {args.kb} not found", file=sys.stderr)
        return 2
    if args.repair:
        result = await rt.consistency.repair(kb.org_id, kb.id)
        _print(
            {
                "reindexed_documents": result.reindexed_documents,
                "deleted_qdrant": result.deleted_qdrant,
                "deleted_opensearch": result.deleted_opensearch,
                "report": _report_dict(result.report),
            }
        )
        return 0 if result.report.consistent else 1
    report = await rt.consistency.check(kb.org_id, kb.id)
    _print(_report_dict(report))
    return 0 if report.consistent else 1


async def _reload_synonyms(rt: IndexingRuntime, args: argparse.Namespace) -> int:
    target = await rt.registry.active() or await rt.registry.bootstrap()
    await rt.backends.text.reload_search_analyzers(target.opensearch_index)
    print(f"search analyzers reloaded on {target.opensearch_index}")
    return 0


Command = Callable[[IndexingRuntime, argparse.Namespace], Awaitable[int]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    groups = parser.add_subparsers(dest="group", required=True)
    index = groups.add_parser("index", help="search index operations")
    cmds = index.add_subparsers(dest="command", required=True)

    cmds.add_parser("bootstrap").set_defaults(func=_bootstrap)
    cmds.add_parser("generations").set_defaults(func=_generations)

    rebuild = cmds.add_parser("rebuild")
    rebuild.add_argument("--embedding-model")
    rebuild.add_argument("--embedding-dim", type=int)
    rebuild.add_argument("--embedding-base-url")
    rebuild.add_argument("--batch-size", type=int, default=100)
    rebuild.add_argument("--strict", action="store_true", help="abort on count mismatch")
    rebuild.add_argument("--no-activate", action="store_true", help="build only, keep aliases")
    rebuild.add_argument("--drop-old", action="store_true", help="drop the previous generation")
    rebuild.set_defaults(func=_rebuild)

    activate = cmds.add_parser("activate")
    activate.add_argument("version", type=int)
    activate.set_defaults(func=_activate)

    drop = cmds.add_parser("drop")
    drop.add_argument("version", type=int)
    drop.set_defaults(func=_drop)

    check = cmds.add_parser("check")
    check.add_argument("--kb", required=True)
    check.add_argument("--repair", action="store_true")
    check.set_defaults(func=_check)

    cmds.add_parser("reload-synonyms").set_defaults(func=_reload_synonyms)

    analytics = groups.add_parser("analytics", help="analytics summaries")
    analytics_cmds = analytics.add_subparsers(dest="command", required=True)
    refresh = analytics_cmds.add_parser("refresh")
    refresh.add_argument("--days", type=int, default=7)
    refresh.add_argument("--org", action="append", dest="orgs", help="org id (repeatable)")

    keycloak = groups.add_parser("keycloak", help="Keycloak realm setup")
    keycloak_cmds = keycloak.add_subparsers(dest="command", required=True)
    setup = keycloak_cmds.add_parser("setup-idp")
    setup.add_argument(
        "--providers", nargs="+", choices=sorted(BRIDGE_PROVIDERS), default=sorted(BRIDGE_PROVIDERS)
    )
    setup.add_argument(
        "--admin-user",
        default=os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME") or os.environ.get("KEYCLOAK_ADMIN"),
        help="master realm admin (default: $KC_BOOTSTRAP_ADMIN_USERNAME / $KEYCLOAK_ADMIN)",
    )
    setup.add_argument(
        "--admin-password",
        default=os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD")
        or os.environ.get("KEYCLOAK_ADMIN_PASSWORD"),
    )
    setup.add_argument(
        "--skip-service-account",
        action="store_true",
        help="do not grant manage-users to the ekb-backend service account",
    )

    agent = groups.add_parser("agent", help="admin assistant")
    agent_cmds = agent.add_subparsers(dest="command", required=True)
    ev = agent_cmds.add_parser("eval", help="evaluate intent understanding on the case set")
    ev.add_argument("--lang", action="append", dest="langs", help="zh / en / vi (repeatable)")
    ev.add_argument("--limit", type=int, default=0)
    ev.add_argument("--no-tools", action="store_true", help="JSON mode only (no function calling)")
    ev.add_argument("--concurrency", type=int, default=4)
    ev.add_argument("--out", help="write the full report (JSON) to this file")

    users = groups.add_parser("users", help="user maintenance")
    users_cmds = users.add_subparsers(dest="command", required=True)
    dups = users_cmds.add_parser("fix-duplicates")
    dups.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")

    evaluation = groups.add_parser("eval", help="offline evaluation / gold gate")
    evaluation_cmds = evaluation.add_subparsers(dest="command", required=True)
    gold = evaluation_cmds.add_parser(
        "gold-check", help="run retrieval gold gate against fixture rankings (CI)"
    )
    gold.add_argument(
        "--cases",
        default=str(Path(__file__).resolve().parents[1] / "tests/fixtures/retrieval_gold.jsonl"),
    )
    gold.add_argument(
        "--rankings",
        default=str(
            Path(__file__).resolve().parents[1] / "tests/fixtures/retrieval_gold_rankings.json"
        ),
    )
    return parser


async def _keycloak_setup_idp(settings: Settings, args: argparse.Namespace) -> int:
    if not args.admin_user or not args.admin_password:
        print("--admin-user / --admin-password are required", file=sys.stderr)
        return 2
    result: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=30) as http:
        admin = KeycloakAdmin.master_admin(http, settings, args.admin_user, args.admin_password)
        result["user_profile_relaxed"] = await admin.relax_user_profile()
        result["broker_flow_created"] = await admin.ensure_broker_flow()
        result["identity_providers"] = {}
        for alias in args.providers:
            payload = identity_provider(
                alias,
                public_base_url=settings.public_base_url,
                internal_base_url=settings.oidc_bridge_internal_url,
                client_id=settings.oidc_bridge_client_id,
                client_secret=settings.oidc_bridge_client_secret,
            )
            result["identity_providers"][alias] = await admin.upsert_identity_provider(payload)
        if not args.skip_service_account:
            result["service_account_roles_added"] = await admin.grant_service_account(
                settings.keycloak_admin_client_id, ["manage-users", "view-users"]
            )
    _print(result)
    return 0


async def _analytics_refresh(settings: Settings, args: argparse.Namespace) -> int:
    engine = create_engine(settings)
    try:
        aggregator = AnalyticsAggregator(create_session_factory(engine), settings)
        result = await aggregator.run_once(args.days, org_ids=args.orgs)
        _print(asdict(result))
    finally:
        await engine.dispose()
    return 0


async def _users_fix_duplicates(settings: Settings, args: argparse.Namespace) -> int:
    engine = create_engine(settings)
    cache = RedisCache.from_url(settings.redis_url)
    try:
        async with create_session_factory(engine)() as session:
            authz = AuthzCache(cache, settings.authz_cache_ttl_seconds)
            result = await fix_case_duplicates(session, authz, apply=args.apply)
            if args.apply:
                await session.commit()
        _print({"apply": args.apply, "groups": result})
    finally:
        await cache.close()
        await engine.dispose()
    return 0


async def _agent_eval(settings: Settings, args: argparse.Namespace) -> int:
    today = datetime.now(ZoneInfo(settings.analytics_timezone)).date()
    cases = [c for c in load_cases(today=today) if not args.langs or c["lang"] in args.langs]
    if args.limit:
        cases = cases[: args.limit]
    engine = create_engine(settings)
    gateway = build_llm_gateway(settings)
    # Same chat model as the running app (model admin page routing).
    attach_chat_routing(gateway, create_session_factory(engine), settings)
    semaphore = asyncio.Semaphore(max(1, args.concurrency))

    async def one(case: dict[str, Any]) -> Any:
        async with semaphore:
            return await run_case(gateway, case, native_tools=not args.no_tools, today=today)

    try:
        results = await asyncio.gather(*(one(c) for c in cases))
    finally:
        await engine.dispose()
    report = {"model": gateway.chat.model, "native_tools": not args.no_tools, **summarize(results)}
    if args.out:
        text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        await asyncio.to_thread(Path(args.out).write_text, text, encoding="utf-8")
    _print({k: report[k] for k in ("model", "native_tools", "summary")})
    for failure in report["failures"]:
        got = failure.get("got") or {}
        print(
            f"FAIL {failure['id']}: intent={got.get('intent')} "
            f"tasks={[t.get('type') for t in got.get('tasks', [])]} "
            f"slots {failure['slots_matched']}/{failure['slots_expected']} "
            f"invented={failure['invented']} error={failure['error']}",
            file=sys.stderr,
        )
    return 0


async def _eval_gold_check(settings: Settings, args: argparse.Namespace) -> int:
    from app.services.evaluation.gold_gate import load_gold_cases, run_gold_gate

    del settings  # offline fixture gate
    cases = load_gold_cases(Path(args.cases))
    raw = await asyncio.to_thread(Path(args.rankings).read_text, encoding="utf-8")
    rankings = json.loads(raw)
    results = run_gold_gate(cases, rankings)
    failed = [r for r in results if not r.passed]
    _print({"total": len(results), "failed": len(failed)})
    for r in failed:
        print(f"FAIL {r.case_id}: {', '.join(r.failures)}", file=sys.stderr)
    return 1 if failed else 0


async def run(argv: list[str], settings: Settings, runtime: IndexingRuntime | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.group == "analytics":
        return await _analytics_refresh(settings, args)
    if args.group == "agent":
        return await _agent_eval(settings, args)
    if args.group == "users":
        return await _users_fix_duplicates(settings, args)
    if args.group == "keycloak":
        return await _keycloak_setup_idp(settings, args)
    if args.group == "eval":
        return await _eval_gold_check(settings, args)
    rt = runtime or IndexingRuntime.create(settings)
    try:
        func: Command = args.func
        return await func(rt, args)
    except (GenerationConflictError, RebuildVerificationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if runtime is None:
            await rt.aclose()


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    sys.exit(asyncio.run(run(sys.argv[1:], settings)))


if __name__ == "__main__":
    main()
