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
eval graph-gate [--cases PATH] [--rankings PATH] [--min-lift 0.15]
                               multi-hop graph lift gate (≥15% recall@5 vs graph-off)
eval seed-dataset --name NAME --cases PATH [--org ORG] [--replace]
                               import JSONL cases (expected_document_titles) into a dataset
eval start-run --dataset-id ID|--name NAME [--org ORG] [--no-judge] [--profile PROFILE]
                               enqueue an offline eval run for a seeded dataset

terminology seed-it-ops [--org ORG_ID]
                               upsert sample IT-ops terminology aliases (idempotent)
terminology retag-chunks [--org ORG_ID] [--document DOCUMENT_ID]
                               recompute chunks.entity_ids from the terminology table
terminology sync-synonyms [--org ORG_ID] [--output PATH] [--no-reload]
                               export active aliases into OpenSearch synonyms.txt and reload

structured seed-equipment [--org ORG_ID]
structured seed-mfg [--org ORG_ID]
                               upsert manufacturing closed-loop fixture ABox (VN delay + identity)
structured wire-mes-chain [--org ORG_ID] [--source NAME]
                               terminology + links + publish Studio for MES device_info Agent debug
                               upsert sample equipment MES mirror + terminology links
structured sync --source-id ID | --source NAME [--org ORG] [--dry-run] [--force-full]
                               pull CSV/REST/MySQL connector configured on a structured source
structured probe-mysql --host H --database DB --table T --user U [--password-env ENV]
                               read-only DESCRIBE + sample rows (password from env; never log it)

ontology validate [--ttl PATH]
                               check enterprise.ttl covers StrEnum classes / relations
ontology export-sample [--out PATH]
                               write Protégé-only sample ABox TTL (not a runtime source)
ontology accept-mfg [--org ORG_ID] [--user USERNAME] [--no-reseed]
                               deterministic manufacturing closed-loop acceptance gate

documents reprocess --kb KB_ID [--org ORG] [--failed] [--missing-pages] [--ids a,b]
                    [--limit N] [--dry-run]
                               batch re-enqueue document parse (ops; no ACL)
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
    graph_gate = evaluation_cmds.add_parser(
        "graph-gate",
        help="multi-hop graph lift gate: with_graph vs without_graph rankings (≥15%)",
    )
    graph_gate.add_argument(
        "--cases",
        default=str(
            Path(__file__).resolve().parents[1] / "tests/fixtures/retrieval_graph_gold.jsonl"
        ),
    )
    graph_gate.add_argument(
        "--rankings",
        default=str(
            Path(__file__).resolve().parents[1]
            / "tests/fixtures/retrieval_graph_gold_rankings.json"
        ),
    )
    graph_gate.add_argument(
        "--min-lift",
        type=float,
        default=0.15,
        help="minimum relative (or absolute if baseline is 0) lift on mean recall@5",
    )
    seed_ds = evaluation_cmds.add_parser(
        "seed-dataset",
        help="import JSONL eval cases keyed by document titles into a dataset",
    )
    seed_ds.add_argument("--name", required=True, help="dataset name (unique per org)")
    seed_ds.add_argument(
        "--cases",
        required=True,
        help="JSONL with question / expected_document_titles / reference_answer",
    )
    seed_ds.add_argument("--org", default="default", help="organization id")
    seed_ds.add_argument(
        "--description",
        default=None,
        help="optional dataset description",
    )
    seed_ds.add_argument(
        "--replace",
        action="store_true",
        help="replace cases if the dataset name already exists",
    )
    start_run = evaluation_cmds.add_parser(
        "start-run", help="enqueue an offline evaluation run for a dataset"
    )
    start_run.add_argument("--dataset-id", default=None)
    start_run.add_argument("--name", default=None, help="dataset name (if no --dataset-id)")
    start_run.add_argument("--org", default="default")
    start_run.add_argument("--profile", default="builtin")
    start_run.add_argument("--run-name", default=None)
    start_run.add_argument(
        "--no-judge",
        action="store_true",
        help="retrieval metrics only (skip LLM judge)",
    )
    start_run.add_argument(
        "--user",
        default="alice",
        help="username used as the run actor (must exist; ACL applies)",
    )

    terminology = groups.add_parser("terminology", help="terminology / alias dictionary")
    terminology_cmds = terminology.add_subparsers(dest="command", required=True)
    seed = terminology_cmds.add_parser("seed-it-ops", help="upsert sample IT-ops terms")
    seed.add_argument("--org", default="default", help="organization id (default: default)")
    retag = terminology_cmds.add_parser(
        "retag-chunks", help="recompute chunks.entity_ids from terminology aliases"
    )
    retag.add_argument("--org", default="default", help="organization id (default: default)")
    retag.add_argument("--document", default=None, help="optional document id to retag")
    sync_syn = terminology_cmds.add_parser(
        "sync-synonyms",
        help="export active terminology into OpenSearch synonyms.txt and reload analyzers",
    )
    sync_syn.add_argument("--org", default="default", help="organization id (default: default)")
    sync_syn.add_argument(
        "--output",
        default=None,
        help="synonyms file path (default: $OPENSEARCH_SYNONYMS_FILE)",
    )
    sync_syn.add_argument(
        "--no-reload",
        action="store_true",
        help="write the file only; do not call OpenSearch reload_search_analyzers",
    )

    structured = groups.add_parser("structured", help="ERP/MES structured equipment mirror")
    structured_cmds = structured.add_subparsers(dest="command", required=True)
    seed_eq = structured_cmds.add_parser(
        "seed-equipment", help="upsert sample equipment MES mirror + terminology links"
    )
    seed_eq.add_argument("--org", default="default", help="organization id (default: default)")
    seed_mfg = structured_cmds.add_parser(
        "seed-mfg",
        help="upsert manufacturing closed-loop fixture (production_order / inventory / identity)",
    )
    seed_mfg.add_argument("--org", default="default", help="organization id (default: default)")
    sync_eq = structured_cmds.add_parser(
        "sync",
        help="pull a CSV/REST connector into equip_* mirror tables for one source",
    )
    sync_eq.add_argument("--org", default="default", help="organization id (default: default)")
    sync_eq.add_argument("--source-id", default=None, help="structured source id")
    sync_eq.add_argument("--source", default=None, help="structured source name")
    sync_eq.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and count would-be upserts without writing",
    )
    sync_eq.add_argument(
        "--force-full",
        action="store_true",
        help="ignore stored sync_cursor and pull a full snapshot",
    )
    wire_mes = structured_cmds.add_parser(
        "wire-mes-chain",
        help="wire MES device_info → terminology links → publish Ontology Studio (Agent debug)",
    )
    wire_mes.add_argument("--org", default="973c4ed04fcc45ac882713ad04523c39")
    wire_mes.add_argument("--source", default="MES device_info")
    probe_mysql = structured_cmds.add_parser(
        "probe-mysql",
        help="read-only MySQL table schema + samples for Steward column_map",
    )
    probe_mysql.add_argument("--host", required=True)
    probe_mysql.add_argument("--port", type=int, default=3306)
    probe_mysql.add_argument("--database", required=True)
    probe_mysql.add_argument("--table", default="device_info")
    probe_mysql.add_argument("--user", required=True)
    probe_mysql.add_argument(
        "--password-env",
        default="MES_MYSQL_PASSWORD",
        help="env var holding the password (default MES_MYSQL_PASSWORD)",
    )
    probe_mysql.add_argument("--sample-limit", type=int, default=3)

    ontology = groups.add_parser("ontology", help="OWL TBox contract (no SPARQL / RDF store)")
    ontology_cmds = ontology.add_subparsers(dest="command", required=True)
    ont_validate = ontology_cmds.add_parser(
        "validate", help="assert enterprise.ttl covers backend StrEnum catalog"
    )
    ont_validate.add_argument(
        "--ttl",
        default=None,
        help="path to enterprise.ttl (default: <repo>/ontology/enterprise.ttl)",
    )
    ont_export = ontology_cmds.add_parser(
        "export-sample",
        help="write read-only seed ABox TTL for Protégé preview",
    )
    ont_export.add_argument(
        "--out",
        default=None,
        help="output path (default: <repo>/ontology/examples/seed-abox.ttl)",
    )
    ont_accept = ontology_cmds.add_parser(
        "accept-mfg",
        help="deterministic manufacturing ontology closed-loop acceptance (seed→query→transfer→audit)",
    )
    ont_accept.add_argument("--org", default="default", help="organization id")
    ont_accept.add_argument(
        "--user",
        default=None,
        help="actor username in org (default: first user in org)",
    )
    ont_accept.add_argument(
        "--no-reseed",
        action="store_true",
        help="skip seed-mfg (use existing fixture rows)",
    )

    documents = groups.add_parser("documents", help="document ingest operations")
    documents_cmds = documents.add_subparsers(dest="command", required=True)
    reprocess = documents_cmds.add_parser(
        "reprocess", help="batch re-enqueue parse for a knowledge base"
    )
    reprocess.add_argument("--org", default="default", help="organization id (default: default)")
    reprocess.add_argument("--kb", required=True, help="knowledge base id")
    reprocess.add_argument(
        "--failed", action="store_true", help="only documents in failed status"
    )
    reprocess.add_argument(
        "--missing-pages",
        action="store_true",
        help="only documents that expected page images but have none / an extract error",
    )
    reprocess.add_argument(
        "--ids",
        default=None,
        help="comma-separated document ids (overrides --failed / --missing-pages)",
    )
    reprocess.add_argument("--limit", type=int, default=100, help="max documents (default 100)")
    reprocess.add_argument(
        "--dry-run", action="store_true", help="list candidates without enqueueing"
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


async def _eval_graph_gate(settings: Settings, args: argparse.Namespace) -> int:
    from app.services.evaluation.gold_gate import (
        load_gold_cases,
        load_graph_rankings,
        run_graph_lift_gate,
    )

    del settings  # offline fixture gate
    cases = load_gold_cases(Path(args.cases))
    without, with_graph = load_graph_rankings(Path(args.rankings))
    report = run_graph_lift_gate(
        cases, without, with_graph, min_lift=float(args.min_lift)
    )
    _print(
        {
            "cases": len(cases),
            "metric": report.metric,
            "without": report.without,
            "with_graph": report.with_graph,
            "lift": report.lift,
            "min_lift": report.min_lift,
            "passed": report.passed,
        }
    )
    for failure in report.failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return 0 if report.passed else 1


async def _eval_seed_dataset(settings: Settings, args: argparse.Namespace) -> int:
    from app.models import Organization
    from app.services.evaluation.seed_baseline import seed_dataset_from_jsonl
    from sqlalchemy import select

    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            org = await session.scalar(select(Organization).where(Organization.id == args.org))
            if org is None:
                # Local demos often use a generated org id; fall back to the first org
                # when --org=default and that literal id is missing.
                if args.org == "default":
                    org = await session.scalar(select(Organization).order_by(Organization.created_at))
                if org is None:
                    print(f"error: organization not found: {args.org}", file=sys.stderr)
                    return 2
            try:
                result = await seed_dataset_from_jsonl(
                    session,
                    org_id=org.id,
                    name=args.name,
                    cases_path=Path(args.cases),
                    description=args.description,
                    replace=bool(args.replace),
                )
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            await session.commit()
        _print({"org_id": org.id, **result})
    finally:
        await engine.dispose()
    return 0


async def _eval_start_run(settings: Settings, args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.models import EvalDataset, Organization, User
    from app.schemas.evaluation import EvalRunCreate
    from app.services.audit_service import AuditContext
    from app.services.authz.context import CurrentUser
    from app.services.authz.principals import PrincipalResolver
    from app.services.context import RequestContext
    from app.services.evaluation.eval_service import EvalService
    from app.services.ingest.queue import DramatiqTaskQueue

    engine = create_engine(settings)
    redis = RedisCache.from_url(settings.redis_url)
    authz = AuthzCache(redis, settings.authz_cache_ttl_seconds)
    try:
        async with create_session_factory(engine)() as session:
            org = await session.scalar(select(Organization).where(Organization.id == args.org))
            if org is None and args.org == "default":
                org = await session.scalar(select(Organization).order_by(Organization.created_at))
            if org is None:
                print(f"error: organization not found: {args.org}", file=sys.stderr)
                return 2
            user = await session.scalar(
                select(User).where(User.org_id == org.id, User.username == args.user)
            )
            if user is None:
                print(f"error: user not found: {args.user}", file=sys.stderr)
                return 2
            if args.dataset_id:
                ds = await session.get(EvalDataset, args.dataset_id)
            elif args.name:
                ds = await session.scalar(
                    select(EvalDataset).where(
                        EvalDataset.org_id == org.id, EvalDataset.name == args.name
                    )
                )
            else:
                print("error: provide --dataset-id or --name", file=sys.stderr)
                return 2
            if ds is None or ds.org_id != org.id:
                print("error: dataset not found", file=sys.stderr)
                return 2
            principals = await PrincipalResolver(session, authz).resolve(org.id, user.id)
            actor = CurrentUser(
                id=user.id,
                org_id=org.id,
                username=user.username,
                display_name=user.display_name,
                principals=principals,
            )
            ctx = RequestContext(
                actor,
                AuditContext(org_id=org.id, actor_id=user.id, actor_name=user.username),
            )
            service = EvalService(
                session, ctx, authz, settings=settings, queue=DramatiqTaskQueue()
            )
            run = await service.create_run(
                EvalRunCreate(
                    dataset_id=ds.id,
                    profile_id=args.profile,
                    name=args.run_name,
                    judge_enabled=not bool(args.no_judge),
                )
            )
            await session.commit()
        _print(run.model_dump(mode="json"))
    finally:
        await redis.close()
        await engine.dispose()
    return 0


async def _terminology_seed_it_ops(settings: Settings, args: argparse.Namespace) -> int:
    from app.services.terminology.seed_it_ops import seed_it_ops

    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            counts = await seed_it_ops(session, args.org)
            await session.commit()
        _print({"org_id": args.org, **counts})
    finally:
        await engine.dispose()
    return 0


async def _terminology_sync_synonyms(settings: Settings, args: argparse.Namespace) -> int:
    from app.repositories.terminology_repo import TerminologyRepository
    from app.services.terminology.synonyms import format_synonym_lines, write_synonyms_file

    target = Path(args.output) if args.output else None
    if target is None:
        if not settings.opensearch_synonyms_file:
            print("error: set --output or OPENSEARCH_SYNONYMS_FILE", file=sys.stderr)
            return 2
        target = Path(settings.opensearch_synonyms_file)

    engine = create_engine(settings)
    rt: IndexingRuntime | None = None
    try:
        async with create_session_factory(engine)() as session:
            rows = await TerminologyRepository(session).load_active_alias_map(args.org)
            lines = format_synonym_lines(rows)
            count = write_synonyms_file(target, lines)
        reloaded = False
        if not args.no_reload:
            rt = IndexingRuntime.create(settings)
            active = await rt.registry.active() or await rt.registry.bootstrap()
            await rt.backends.text.reload_search_analyzers(active.opensearch_index)
            reloaded = True
        _print({"org_id": args.org, "path": str(target), "lines": count, "reloaded": reloaded})
        return 0
    finally:
        if rt is not None:
            await rt.aclose()
        await engine.dispose()


async def _terminology_retag_chunks(settings: Settings, args: argparse.Namespace) -> int:
    from app.services.terminology.retag import retag_chunks

    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            counts = await retag_chunks(session, args.org, document_id=args.document)
            await session.commit()
        _print({"org_id": args.org, "document_id": args.document, **counts})
    finally:
        await engine.dispose()
    return 0


async def _structured_wire_mes_chain(settings: Settings, args: argparse.Namespace) -> int:
    from app.services.structured.wire_mes_chain import wire_mes_debug_chain

    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            out = await wire_mes_debug_chain(session, args.org, source_name=args.source)
            await session.commit()
        _print(out)
    finally:
        await engine.dispose()
    return 0


async def _structured_seed_equipment(settings: Settings, args: argparse.Namespace) -> int:
    from app.services.structured.seed_equipment import seed_equipment

    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            counts = await seed_equipment(session, args.org)
            await session.commit()
        _print({"org_id": args.org, **counts})
    finally:
        await engine.dispose()
    return 0


async def _structured_seed_mfg(settings: Settings, args: argparse.Namespace) -> int:
    from app.services.structured.seed_mfg import seed_mfg

    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            counts = await seed_mfg(session, args.org)
            await session.commit()
        _print({"org_id": args.org, **counts})
    finally:
        await engine.dispose()
    return 0


def _structured_probe_mysql(args: argparse.Namespace) -> int:
    from app.services.structured.connectors.mysql import probe_mysql_table

    password = os.environ.get(args.password_env) or ""
    if not password:
        print(f"missing password: set env {args.password_env}", file=sys.stderr)
        return 2
    try:
        out = probe_mysql_table(
            host=args.host,
            port=args.port,
            user=args.user,
            password=password,
            database=args.database,
            table=args.table,
            sample_limit=args.sample_limit,
        )
    except Exception as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    try:
        print(payload)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((payload + "\n").encode("utf-8", errors="replace"))
    return 0


async def _structured_sync(settings: Settings, args: argparse.Namespace) -> int:
    from app.repositories.structured_repo import StructuredRepository
    from app.services.structured.sync import StructuredSyncExecutor

    if not args.source_id and not args.source:
        print("error: provide --source-id or --source", file=sys.stderr)
        return 2

    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            repo = StructuredRepository(session)
            source_id = args.source_id
            if not source_id:
                row = await repo.get_source_by_name(args.org, args.source)
                if row is None:
                    print(f"error: source not found: {args.source}", file=sys.stderr)
                    return 1
                source_id = row.id
            result = await StructuredSyncExecutor(session, settings).sync_source(
                args.org,
                source_id,
                dry_run=bool(args.dry_run),
                force_full=bool(getattr(args, "force_full", False)),
                triggered_by="cli",
            )
            if not args.dry_run:
                await session.commit()
            else:
                await session.rollback()
        _print(result)
    finally:
        await engine.dispose()
    return 0


async def _ontology_validate(settings: Settings, args: argparse.Namespace) -> int:
    from app.ontology.validate_ttl import validate_enterprise_ttl

    del settings
    ttl = Path(args.ttl) if args.ttl else None
    issues = validate_enterprise_ttl(ttl)
    _print(
        {
            "ok": not issues,
            "ttl": str(ttl) if ttl else "ontology/enterprise.ttl",
            "issues": [{"code": i.code, "message": i.message} for i in issues],
        }
    )
    return 1 if issues else 0


async def _ontology_export_sample(settings: Settings, args: argparse.Namespace) -> int:
    from app.ontology.export_sample import write_seed_abox

    del settings
    out = write_seed_abox(Path(args.out) if args.out else None)
    _print({"written": str(out)})
    return 0


async def _ontology_accept_mfg(settings: Settings, args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.models import Organization, User
    from app.services.audit_service import AuditContext
    from app.services.authz.context import CurrentUser
    from app.services.authz.principals import PrincipalResolver, Principals
    from app.services.context import RequestContext
    from app.services.ontology_studio.accept_mfg import run_mfg_acceptance

    engine = create_engine(settings)
    redis = RedisCache.from_url(settings.redis_url)
    authz = AuthzCache(redis, settings.authz_cache_ttl_seconds)
    try:
        async with create_session_factory(engine)() as session:
            org = await session.scalar(
                select(Organization).where(Organization.id == args.org)
            )
            if org is None and args.org == "default":
                org = await session.scalar(
                    select(Organization).order_by(Organization.created_at)
                )
            if org is None:
                print(f"error: organization not found: {args.org}", file=sys.stderr)
                return 2
            user_row = None
            if args.user:
                user_row = await session.scalar(
                    select(User).where(
                        User.org_id == org.id, User.username == args.user
                    )
                )
            else:
                user_row = await session.scalar(
                    select(User)
                    .where(User.org_id == org.id)
                    .order_by(User.created_at.asc())
                )
            if user_row is None:
                print(
                    "error: no user in org (pass --user USERNAME)",
                    file=sys.stderr,
                )
                return 2
            try:
                principals = await PrincipalResolver(session, authz).resolve(
                    org.id, user_row.id
                )
            except Exception:  # noqa: BLE001 — offline / sparse orgs
                principals = Principals(org.id, user_row.id)
            actor = CurrentUser(
                id=user_row.id,
                org_id=org.id,
                username=user_row.username,
                display_name=user_row.display_name,
                principals=principals,
                permissions=frozenset({"*", "admin:retrieval"}),
            )
            report = await run_mfg_acceptance(
                session,
                org_id=org.id,
                user=actor,
                reseeds=not bool(args.no_reseed),
            )
            if report.ok:
                await session.commit()
            else:
                await session.rollback()
            _print(report.to_dict())
            return 0 if report.ok else 1
    finally:
        await redis.close()
        await engine.dispose()


async def _documents_reprocess(settings: Settings, args: argparse.Namespace) -> int:
    """Ops batch reprocess: resets status to uploaded and enqueues parse (no ACL)."""
    from app.models import Document, DocumentStatus
    from app.repositories.knowledge_repo import DocumentRepository
    from app.services.ingest.queue import DramatiqTaskQueue

    ids = [x.strip() for x in (args.ids or "").split(",") if x.strip()]
    status = DocumentStatus.FAILED.value if args.failed and not ids else None
    engine = create_engine(settings)
    queue = DramatiqTaskQueue()
    try:
        async with create_session_factory(engine)() as session:
            repo = DocumentRepository(session)
            if ids:
                stmt = repo.search_stmt(args.org, args.kb).where(Document.id.in_(ids))
            else:
                stmt = repo.search_stmt(
                    args.org,
                    args.kb,
                    status=status,
                    missing_page_images=bool(args.missing_pages),
                )
            docs = list((await session.execute(stmt.limit(max(1, args.limit)))).scalars())
            queued: list[str] = []
            skipped: list[dict[str, str]] = []
            for doc in docs:
                if doc.status == DocumentStatus.PARSING.value:
                    skipped.append({"id": doc.id, "reason": "parsing"})
                    continue
                if args.dry_run:
                    queued.append(doc.id)
                    continue
                doc.status = DocumentStatus.UPLOADED.value
                doc.error_message = None
                await session.flush()
                queue.enqueue_parse(doc.id, doc.version)
                queued.append(doc.id)
            if not args.dry_run:
                await session.commit()
        _print(
            {
                "org_id": args.org,
                "kb_id": args.kb,
                "dry_run": bool(args.dry_run),
                "queued": queued,
                "skipped": skipped,
                "total_candidates": len(docs),
            }
        )
    finally:
        await engine.dispose()
    return 0


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
        if args.command == "graph-gate":
            return await _eval_graph_gate(settings, args)
        if args.command == "seed-dataset":
            return await _eval_seed_dataset(settings, args)
        if args.command == "start-run":
            return await _eval_start_run(settings, args)
        return await _eval_gold_check(settings, args)
    if args.group == "terminology":
        if args.command == "retag-chunks":
            return await _terminology_retag_chunks(settings, args)
        if args.command == "sync-synonyms":
            return await _terminology_sync_synonyms(settings, args)
        return await _terminology_seed_it_ops(settings, args)
    if args.group == "structured":
        if args.command == "sync":
            return await _structured_sync(settings, args)
        if args.command == "probe-mysql":
            return _structured_probe_mysql(args)
        if args.command == "wire-mes-chain":
            return await _structured_wire_mes_chain(settings, args)
        if args.command == "seed-mfg":
            return await _structured_seed_mfg(settings, args)
        return await _structured_seed_equipment(settings, args)
    if args.group == "ontology":
        if args.command == "export-sample":
            return await _ontology_export_sample(settings, args)
        if args.command == "accept-mfg":
            return await _ontology_accept_mfg(settings, args)
        return await _ontology_validate(settings, args)
    if args.group == "documents":
        return await _documents_reprocess(settings, args)
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
