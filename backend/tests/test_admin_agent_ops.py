"""Admin assistant, second batch: reverse operations, departments, roles, audit log, platform
status lookups and starting an offline evaluation. The model is scripted; everything else is real.
"""

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import create_session_factory
from app.llm import LLMGateway
from app.models import Department, ResourceAcl, Role, User
from app.repositories.role_repo import RoleRepository
from app.repositories.user_repo import UserRepository
from app.services.ingest.queue import RecordingTaskQueue
from tests.test_admin_agent import ALICE, RUNS, login, of, post_sse, script, stages, understood


async def plan_of(api: httpx.AsyncClient, llm_gateway: LLMGateway, *tasks: Any) -> dict[str, Any]:
    script(llm_gateway, understood(*tasks))
    events = await post_sse(api, RUNS, {"message": "x"})
    plans = of(events, "plan")
    assert plans, of(events, "clarify")
    return plans[0]


async def execute(api: httpx.AsyncClient, plan: dict[str, Any], ack: bool = False) -> list[Any]:
    return await post_sse(api, f"{RUNS}/{plan['run_id']}/execute", {"acknowledge_risk": ack})


async def clarify_of(
    api: httpx.AsyncClient, llm_gateway: LLMGateway, *tasks: Any
) -> dict[str, Any]:
    script(llm_gateway, understood(*tasks))
    events = await post_sse(api, RUNS, {"message": "x"})
    assert not of(events, "plan")
    item: dict[str, Any] = of(events, "clarify")[0]["items"][0]
    return item


async def query(
    api: httpx.AsyncClient, llm_gateway: LLMGateway, *tasks: Any
) -> list[dict[str, Any]]:
    script(llm_gateway, understood(*tasks, intent="query"), "答复")
    events = await post_sse(api, RUNS, {"message": "查一下"})
    assert of(events, "report")[-1]["outcome"] == "answered"
    return [t for t in of(events, "tool") if t["status"] != "running"]


async def test_revoke_grant_and_remove_roles(
    api: httpx.AsyncClient, engine: AsyncEngine, llm_gateway: LLMGateway
) -> None:
    await login(api)
    await api.post(
        "/api/v1/knowledge-bases",
        json={"name": "撤销库", "visibility": "restricted"},
        headers=ALICE,
    )
    grant = {"principal_type": "user", "principal": "carol", "permission": "edit"}
    setup = await plan_of(
        api,
        llm_gateway,
        {"type": "grant_kb_access", "slots": {"knowledge_base": "撤销库", "grants": [grant]}},
        {"type": "assign_roles", "slots": {"users": ["carol"], "roles": ["kb_editor"]}},
    )
    assert of(await execute(api, setup), "report")[-1]["outcome"] == "done"

    plan = await plan_of(
        api,
        llm_gateway,
        {
            "type": "revoke_kb_access",
            "slots": {"knowledge_base": "撤销库", "principal_type": "user", "principal": "carol"},
        },
        {"type": "remove_roles", "slots": {"users": ["carol"], "roles": ["kb_editor"]}},
    )
    assert [s["tool"] for s in plan["steps"]] == ["remove_roles", "revoke_kb_access"]
    assert plan["steps"][1]["display"]["permission"] == "edit"
    done = await execute(api, plan)

    assert {v["code"] for v in of(done, "verify")} == {"roles_removed", "revoke_ok"}
    async with create_session_factory(engine)() as s:
        carol = (await s.execute(select(User).where(User.username == "carol"))).scalar_one()
        roles = [r.code for r in await UserRepository(s).list_roles(carol.org_id, carol.id)]
        assert "kb_editor" not in roles
        rows = (
            await s.execute(select(ResourceAcl.id).where(ResourceAcl.principal_id == carol.id))
        ).all()
        assert rows == []

    again = await clarify_of(
        api,
        llm_gateway,
        {
            "type": "revoke_kb_access",
            "slots": {"knowledge_base": "撤销库", "principal_type": "user", "principal": "carol"},
        },
    )
    assert again["reason"] == "no_grant"


async def test_disable_and_enable_accounts(
    api: httpx.AsyncClient, engine: AsyncEngine, llm_gateway: LLMGateway
) -> None:
    await login(api)
    plan = await plan_of(api, llm_gateway, {"type": "disable_users", "slots": {"user": "bob"}})
    assert plan["risk"] == "medium"
    assert plan["steps"][0]["risk_reasons"][0]["code"] == "disable_users"
    done = await execute(api, plan)
    assert of(done, "verify")[0]["code"] == "users_disabled"
    async with create_session_factory(engine)() as s:
        bob = (await s.execute(select(User).where(User.username == "bob"))).scalar_one()
        assert bob.is_active is False

    already = await clarify_of(
        api, llm_gateway, {"type": "disable_users", "slots": {"users": ["bob"]}}
    )
    assert already["reason"] == "already_disabled"
    plan = await plan_of(api, llm_gateway, {"type": "enable_users", "slots": {"users": ["bob"]}})
    assert of(await execute(api, plan), "verify")[0]["code"] == "users_enabled"

    myself = await clarify_of(
        api, llm_gateway, {"type": "disable_users", "slots": {"users": ["alice"]}}
    )
    assert myself["reason"] == "cannot_disable_self"


async def test_departments_created_in_one_plan_are_usable_by_later_steps(
    api: httpx.AsyncClient, engine: AsyncEngine, llm_gateway: LLMGateway
) -> None:
    await login(api)
    plan = await plan_of(
        api,
        llm_gateway,
        {
            "type": "onboard_user",
            "slots": {"username": "ping", "display_name": "平平", "department": "平台组"},
        },
        {"type": "create_department", "slots": {"name": "研发中心"}},
        {"type": "create_department", "slots": {"name": "平台组", "parent": "研发中心"}},
    )
    assert [s["tool"] for s in plan["steps"]] == [
        "create_department",
        "create_department",
        "create_user",
    ]
    assert plan["steps"][2]["display"]["department"] == "研发中心 / 平台组"
    done = await execute(api, plan)
    assert of(done, "report")[-1]["outcome"] == "done", of(done, "step")
    async with create_session_factory(engine)() as s:
        user = (await s.execute(select(User).where(User.username == "ping"))).scalar_one()
        dept = (await s.execute(select(Department).where(Department.name == "平台组"))).scalar_one()
        assert dept.id in await UserRepository(s).department_ids(user.org_id, user)

    exists = await clarify_of(
        api, llm_gateway, {"type": "create_department", "slots": {"name": "研发中心"}}
    )
    assert exists["reason"] == "dept_exists"

    plan = await plan_of(
        api,
        llm_gateway,
        {"type": "rename_department", "slots": {"department": "平台组", "name": "平台部"}},
    )
    assert of(await execute(api, plan), "verify")[0]["code"] == "dept_renamed"
    plan = await plan_of(
        api, llm_gateway, {"type": "move_department", "slots": {"department": "平台部"}}
    )
    assert plan["risk"] == "medium"  # one user moves with it
    assert of(await execute(api, plan), "verify")[0]["code"] == "dept_moved"
    async with create_session_factory(engine)() as s:
        dept = (await s.execute(select(Department).where(Department.name == "平台部"))).scalar_one()
        assert dept.parent_id is None

    cycle = await clarify_of(
        api,
        llm_gateway,
        {"type": "move_department", "slots": {"department": "研发中心", "parent": "研发中心"}},
    )
    assert cycle["reason"] == "dept_cycle"


async def test_role_creation_and_permission_changes_are_gated(
    api: httpx.AsyncClient, engine: AsyncEngine, llm_gateway: LLMGateway
) -> None:
    await login(api)
    plan = await plan_of(
        api,
        llm_gateway,
        {
            "type": "create_role",
            "slots": {
                "code": "auditor",
                "name": "审计员",
                "permissions": ["admin:audit", "kb:read"],
            },
        },
        {"type": "assign_roles", "slots": {"users": ["carol"], "roles": ["auditor"]}},
    )
    assert [s["tool"] for s in plan["steps"]] == ["create_role", "assign_roles"]
    assert plan["risk"] == "high" and plan["needs_ack"]
    assert of(await execute(api, plan), "error")[0]["reason"] == "risk_ack_required"
    done = await execute(api, plan, ack=True)
    assert {v["code"] for v in of(done, "verify")} == {"role_created", "roles_ok"}

    plan = await plan_of(
        api,
        llm_gateway,
        {"type": "update_role_permissions", "slots": {"role": "auditor", "add": "doc:upload"}},
    )
    step = plan["steps"][0]
    assert step["display"]["added"] == "doc:upload" and step["display"]["users"] == "1"
    assert plan["risk"] == "high"  # the role is in use
    done = await execute(api, plan, ack=True)
    assert of(done, "verify")[0]["code"] == "role_permissions_ok"
    async with create_session_factory(engine)() as s:
        role = (await s.execute(select(Role).where(Role.code == "auditor"))).scalar_one()
        perms = await RoleRepository(s).permission_codes_by_role(role.org_id, [role.id])
        assert sorted(perms[role.id]) == ["admin:audit", "doc:upload", "kb:read"]

    unknown = await clarify_of(
        api,
        llm_gateway,
        {"type": "update_role_permissions", "slots": {"role": "auditor", "add": ["doc:fly"]}},
    )
    assert unknown["reason"] == "permission_unknown" and "doc:upload" in unknown["options"]
    default = await clarify_of(
        api,
        llm_gateway,
        {"type": "update_role_permissions", "slots": {"role": "kb_viewer", "add": ["admin:user"]}},
    )
    assert default["reason"] == "default_role_privileged"


async def test_audit_log_query_names_targets_and_acl_changes(
    api: httpx.AsyncClient, llm_gateway: LLMGateway
) -> None:
    await login(api)
    await api.post(
        "/api/v1/knowledge-bases",
        json={"name": "审计库", "visibility": "restricted"},
        headers=ALICE,
    )
    grant = {"principal_type": "user", "principal": "carol", "permission": "read"}
    plan = await plan_of(
        api,
        llm_gateway,
        {"type": "create_group", "slots": {"name": "审计组"}},
        {"type": "grant_kb_access", "slots": {"knowledge_base": "审计库", "grants": [grant]}},
    )
    await execute(api, plan)

    (tool,) = await query(api, llm_gateway, {"type": "audit_logs", "slots": {"action": "group"}})
    assert tool["tool"] == "search_audit_logs"
    items = tool["result"]["items"]
    assert any(i["action"] == "group.create" and i["target"] == "审计组" for i in items)

    (tool,) = await query(
        api,
        llm_gateway,
        {"type": "audit_logs", "slots": {"target": "审计库", "action": "kb.set_acl"}},
    )
    changes = tool["result"]["items"][0]["changes"]
    assert any(c.startswith("+ user:") and c.endswith("→ read") for c in changes)


async def test_platform_status_lookups(api: httpx.AsyncClient, llm_gateway: LLMGateway) -> None:
    await login(api)
    tools = await query(
        api,
        llm_gateway,
        {"type": "model_status", "slots": {}},
        {"type": "index_status", "slots": {}},
        {"type": "api_clients", "slots": {}},
        {"type": "eval_datasets", "slots": {}},
        {"type": "eval_runs", "slots": {}},
    )
    by_tool = {t["tool"]: t for t in tools}
    assert all(t["status"] == "done" for t in tools), [t.get("error") for t in tools]
    assert {"chat", "embedding"} <= {
        s["scene"] for s in by_tool["model_status"]["result"]["scenes"]
    }
    assert set(by_tool["index_status"]["result"]["outbox"]) >= {"pending", "dead"}
    assert by_tool["list_api_clients"]["result"] == []


async def test_offline_evaluation_is_queued_after_commit(
    api: httpx.AsyncClient, llm_gateway: LLMGateway, task_queue: RecordingTaskQueue
) -> None:
    await login(api)
    ds = (
        await api.post("/api/v1/evaluation/datasets", json={"name": "回归集"}, headers=ALICE)
    ).json()
    empty = await clarify_of(
        api, llm_gateway, {"type": "start_eval", "slots": {"dataset": "回归集"}}
    )
    assert empty["reason"] == "dataset_empty"
    case = {"question": "年假几天？"}
    assert (
        await api.post(f"/api/v1/evaluation/datasets/{ds['id']}/cases", json=case, headers=ALICE)
    ).status_code == 201

    plan = await plan_of(
        api, llm_gateway, {"type": "start_eval", "slots": {"dataset": "回归集", "judge": False}}
    )
    assert plan["steps"][0]["display"] == {"dataset": "回归集", "profile": "builtin", "cases": "1"}
    assert task_queue.eval_runs == []
    done = await execute(api, plan)
    assert of(done, "verify")[0]["code"] == "eval_queued"
    assert len(task_queue.eval_runs) == 1

    missing = await clarify_of(
        api, llm_gateway, {"type": "start_eval", "slots": {"dataset": "回归"}}
    )
    assert missing["reason"] == "dataset_not_found" and missing["options"] == ["回归集"]


async def test_relative_dates_get_today_in_the_prompt(
    api: httpx.AsyncClient, llm_gateway: LLMGateway
) -> None:
    await login(api)
    chat = script(llm_gateway, {"language": "zh", "intent": "chitchat", "reply": "好", "tasks": []})
    events = await post_sse(api, RUNS, {"message": "你好"})
    assert ("understand", "done") in stages(events)
    assert "Today is 20" in chat.calls[0][0].content
