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
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.core.logging import setup_logging
from app.llm import EmbeddingSpec
from app.models import KnowledgeBase
from app.services.analytics.aggregator import AnalyticsAggregator
from app.services.indexing.consistency import ConsistencyReport
from app.services.indexing.generations import GenerationConflictError
from app.services.indexing.rebuild import RebuildVerificationError
from app.services.indexing.runtime import IndexingRuntime
from app.services.keycloak_admin import BRIDGE_PROVIDERS, KeycloakAdmin, identity_provider


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


async def run(argv: list[str], settings: Settings, runtime: IndexingRuntime | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.group == "analytics":
        return await _analytics_refresh(settings, args)
    if args.group == "keycloak":
        return await _keycloak_setup_idp(settings, args)
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
