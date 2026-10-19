"""Admin assistant workflow: the model is scripted; gates, templates, checks, rollback are real."""

import dataclasses
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import create_session_factory
from app.llm import ChatMessage, ChatResult, LLMGateway
from app.models import AuditLog, Group, KnowledgeBase, ResourceAcl, User
from app.repositories.user_repo import UserRepository
from app.services.admin_agent import tools as agent_tools
from app.services.admin_agent import verify as agent_verify
from tests.conftest import auth

ALICE, BOB, CAROL = auth("alice-token"), auth("bob-token"), auth("carol-token")
RUNS = "/api/v1/admin/agent/runs"


class ScriptedChat:
    """Returns the queued outputs in order and records every prompt it was given."""

    def __init__(self, outputs: list[Any]) -> None:
        self.outputs: list[ChatResult] = [
            o
            if isinstance(o, ChatResult)
            else ChatResult(
                content=o if isinstance(o, str) else json.dumps(o, ensure_ascii=False),
                model="scripted",
            )
            for o in outputs
        ]
        self.calls: list[list[ChatMessage]] = []
        self.options: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return "scripted"

    async def complete(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        self.calls.append(list(messages))
        self.options.append(options)
        return self.outputs.pop(0)

    async def stream(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[str]:
        yield (await self.complete(messages)).content


def script(gateway: LLMGateway, *outputs: Any) -> ScriptedChat:
    chat = ScriptedChat(list(outputs))
    gateway.chat = chat
    return chat


def understood(
    *tasks: dict[str, Any], language: str = "zh", intent: str = "change"
) -> dict[str, Any]:
    return {"language": language, "intent": intent, "thought": "理解了", "tasks": list(tasks)}


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def post_sse(
    api: httpx.AsyncClient, url: str, body: dict[str, Any], headers: dict[str, str] = ALICE
) -> list[tuple[str, dict[str, Any]]]:
    resp = await api.post(url, json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return parse_sse(resp.text)


def of(events: list[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [data for name, data in events if name == kind]


def stages(events: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, str]]:
    return [(d["stage"], d["status"]) for d in of(events, "stage")]


async def login(api: httpx.AsyncClient) -> None:
    for headers in (ALICE, BOB, CAROL):
        assert (await api.get("/api/v1/auth/me", headers=headers)).status_code == 200


ONBOARD = understood(
    {"type": "create_knowledge_base", "slots": {"name": "IT运维库"}},
    {
        "type": "onboard_user",
        "slots": {
            "username": "Hien",
            "display_name": "Nguyen Minh Hien",
            "employee_no": "26003932",
            "roles": ["kb_editor"],
            "kb_grants": [{"knowledge_base": "IT运维库", "permission": "edit"}],
        },
    },
    {
        "type": "add_to_group",
        "slots": {"group": "ERP 项目组", "users": ["26003932"], "create_group": True},
    },
)


async def test_change_runs_through_every_gate_and_is_verified(
    api: httpx.AsyncClient, engine: AsyncEngine, llm_gateway: LLMGateway
) -> None:
    await login(api)
    chat = script(llm_gateway, ONBOARD)

    events = await post_sse(api, RUNS, {"message": "给 Hien 开账号……"})

    assert len(chat.calls) == 1  # the model only understands; code plans
    assert stages(events) == [
        ("understand", "running"),
        ("understand", "done"),
        ("clarify", "running"),
        ("clarify", "done"),
        ("resolve", "running"),
        ("resolve", "done"),
        ("plan", "done"),
        ("risk", "done"),
        ("approval", "waiting"),
    ]
    assert of(events, "thought")[0]["text"] == "理解了"
    plan = of(events, "plan")[0]
    # Template expansion in fixed phase order, whatever order the admin used.
    assert [s["tool"] for s in plan["steps"]] == [
        "create_knowledge_base",
        "create_group",
        "create_user",
        "add_to_group",
        "assign_roles",
        "grant_kb_access",
    ]
    assert plan["steps"][2]["display"]["user"] == "Nguyen Minh Hien（Hien · 26003932）"
    assert plan["risk"] == "low" and plan["needs_ack"] is False
    assert of(events, "report")[-1]["outcome"] == "awaiting_approval"
    async with create_session_factory(engine)() as s:
        assert (await s.execute(select(User).where(User.username == "Hien"))).first() is None

    done = await post_sse(api, f"{RUNS}/{plan['run_id']}/execute", {})

    assert [d["status"] for d in of(done, "step") if d["status"] != "running"] == ["done"] * 6
    assert [v["ok"] for v in of(done, "verify")] == [True] * 6
    assert {v["code"] for v in of(done, "verify")} >= {"user_created", "grant_ok", "roles_ok"}
    assert of(done, "report")[-1] == {"outcome": "done", "language": "zh", "done": 6}
    async with create_session_factory(engine)() as s:
        user = (await s.execute(select(User).where(User.username == "Hien"))).scalar_one()
        repo = UserRepository(s)
        assert [r.code for r in await repo.list_roles(user.org_id, user.id)] == ["kb_editor"]
        assert [g.name for g in await repo.list_groups(user.org_id, user.id)] == ["ERP 项目组"]
        actions = set((await s.execute(select(AuditLog.action))).scalars())
        assert {"admin_agent.execute", "user.create", "group.create", "kb.set_acl"} <= actions

    again = await post_sse(api, f"{RUNS}/{plan['run_id']}/execute", {})
    assert of(again, "error")[0]["reason"] == "plan_expired"


async def test_english_request_reports_in_english(
    api: httpx.AsyncClient, llm_gateway: LLMGateway
) -> None:
    await login(api)
    chat = script(
        llm_gateway,
        understood(
            {"type": "create_group", "slots": {"name": "ERP Team"}},
            {"type": "add_to_group", "slots": {"group": "ERP Team", "users": ["carol"]}},
            language="en",
        ),
    )

    events = await post_sse(api, RUNS, {"message": "Create ERP Team and add carol to it"})

    assert "<message>\nCreate ERP Team and add carol to it\n</message>" in chat.calls[0][1].content
    plan = of(events, "plan")[0]
    assert [s["tool"] for s in plan["steps"]] == ["create_group", "add_to_group"]
    assert of(events, "report")[-1]["language"] == "en"
    done = await post_sse(api, f"{RUNS}/{plan['run_id']}/execute", {})
    assert of(done, "report")[-1]["outcome"] == "done"


async def test_missing_required_slots_stop_at_clarify(
    api: httpx.AsyncClient, llm_gateway: LLMGateway
) -> None:
    await login(api)
    script(llm_gateway, understood({"type": "onboard_user", "slots": {"display_name": "张三"}}))

    events = await post_sse(api, RUNS, {"message": "给张三开个账号"})

    assert ("clarify", "blocked") in stages(events)
    item = of(events, "clarify")[0]["items"][0]
    assert item["reason"] == "missing_slot" and item["params"]["fields"] == "username"
    assert not of(events, "plan") and of(events, "report")[-1]["outcome"] == "clarify"


async def test_unknown_task_type_is_rejected_by_code(
    api: httpx.AsyncClient, llm_gateway: LLMGateway
) -> None:
    await login(api)
    script(llm_gateway, understood({"type": "delete_all_users", "slots": {}}))

    events = await post_sse(api, RUNS, {"message": "删除所有用户"})

    assert of(events, "clarify")[0]["items"][0] == {
        "reason": "unsupported_task",
        "params": {"task": "delete_all_users"},
    }
    assert not of(events, "plan")


async def test_ambiguous_people_are_offered_as_options(
    api: httpx.AsyncClient, engine: AsyncEngine, llm_gateway: LLMGateway
) -> None:
    await login(api)
    async with create_session_factory(engine)() as s:
        bob = (await s.execute(select(User).where(User.username == "bob"))).scalar_one()
        s.add(User(org_id=bob.org_id, username="bob2", display_name="Bob", employee_no="E1"))
        bob.employee_no = "E1"
        await s.commit()
    script(
        llm_gateway,
        understood({"type": "assign_roles", "slots": {"users": ["E1"], "roles": ["kb_editor"]}}),
    )

    events = await post_sse(api, RUNS, {"message": "给工号 E1 编辑者"})

    item = of(events, "clarify")[0]["items"][0]
    assert item["reason"] == "user_ambiguous" and len(item["options"]) == 2
    assert ("resolve", "blocked") in stages(events)


async def test_failed_step_rolls_back_the_whole_plan(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    llm_gateway: LLMGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await login(api)

    async def boom(*_: Any) -> dict[str, Any]:
        raise RuntimeError("keycloak down")

    monkeypatch.setitem(
        agent_tools.TOOLS,
        "add_to_group",
        dataclasses.replace(agent_tools.TOOLS["add_to_group"], run=boom),
    )
    script(
        llm_gateway,
        understood(
            {"type": "create_group", "slots": {"name": "G1"}},
            {"type": "add_to_group", "slots": {"group": "G1", "users": ["carol"]}},
        ),
    )
    plan = of(await post_sse(api, RUNS, {"message": "x"}), "plan")[0]

    out = await post_sse(api, f"{RUNS}/{plan['run_id']}/execute", {})

    final = {d["index"]: d["status"] for d in of(out, "step")}
    assert final == {0: "rolled_back", 1: "failed"}
    assert ("execute", "failed") in stages(out)
    async with create_session_factory(engine)() as s:
        assert (await s.execute(select(Group).where(Group.name == "G1"))).first() is None


async def test_failed_post_condition_rolls_back(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    llm_gateway: LLMGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await login(api)

    async def never(*_: Any) -> agent_verify.Check:
        return agent_verify.Check(False, "group_missing", {"group": "G2"})

    monkeypatch.setitem(agent_verify.CHECKS, "create_group", never)
    script(llm_gateway, understood({"type": "create_group", "slots": {"name": "G2"}}))
    plan = of(await post_sse(api, RUNS, {"message": "x"}), "plan")[0]

    out = await post_sse(api, f"{RUNS}/{plan['run_id']}/execute", {})

    assert of(out, "verify")[0]["ok"] is False
    failed = next(d for d in of(out, "step") if d["status"] == "failed")
    assert failed["error"]["reason"] == "verify_failed"
    async with create_session_factory(engine)() as s:
        assert (await s.execute(select(Group).where(Group.name == "G2"))).first() is None


async def test_high_risk_plan_needs_acknowledgement(
    api: httpx.AsyncClient, llm_gateway: LLMGateway
) -> None:
    await login(api)
    script(
        llm_gateway,
        understood({"type": "assign_roles", "slots": {"users": ["carol"], "roles": ["kb_admin"]}}),
    )
    plan = of(await post_sse(api, RUNS, {"message": "让 carol 当管理员"}), "plan")[0]
    assert plan["risk"] == "high" and plan["needs_ack"] is True
    assert plan["steps"][0]["risk_reasons"][0]["code"] == "privileged_role"

    blocked = await post_sse(api, f"{RUNS}/{plan['run_id']}/execute", {})
    assert of(blocked, "error")[0]["reason"] == "risk_ack_required"

    done = await post_sse(api, f"{RUNS}/{plan['run_id']}/execute", {"acknowledge_risk": True})
    assert of(done, "report")[-1]["outcome"] == "done"


async def test_query_runs_lookups_and_answers_from_data(
    api: httpx.AsyncClient, llm_gateway: LLMGateway
) -> None:
    await login(api)
    chat = script(
        llm_gateway,
        understood({"type": "user_access", "slots": {"user": "carol"}}, intent="query"),
        "carol 可以访问 0 个知识库。",
    )

    events = await post_sse(api, RUNS, {"message": "carol 能看哪些库"})

    tool = next(t for t in of(events, "tool") if t["status"] == "done")
    assert tool["tool"] == "explain_user_access" and "carol" in json.dumps(tool["result"])
    assert of(events, "answer")[0]["text"] == "carol 可以访问 0 个知识库。"
    assert "<data>" in chat.calls[1][1].content
    assert not of(events, "plan") and of(events, "report")[-1]["outcome"] == "answered"


async def test_chitchat_and_bad_output(api: httpx.AsyncClient, llm_gateway: LLMGateway) -> None:
    await login(api)
    script(llm_gateway, {"language": "en", "intent": "chitchat", "reply": "Hi!", "tasks": []})
    events = await post_sse(api, RUNS, {"message": "hello"})
    assert of(events, "answer")[0]["text"] == "Hi!"

    # native-tools attempt, then JSON mode + one retry: three bad outputs end in an error.
    script(llm_gateway, "not json", "still not json", "nope")
    events = await post_sse(api, RUNS, {"message": "hello"})
    assert of(events, "error")[0]["params"]["message"].startswith("无法理解")


async def test_native_function_call_is_used_and_recorded(
    api: httpx.AsyncClient, engine: AsyncEngine, llm_gateway: LLMGateway
) -> None:
    from app.llm import ToolCall
    from app.models import AgentRun

    await login(api)
    args = json.dumps(understood({"type": "create_group", "slots": {"name": "G9"}}))
    chat = script(
        llm_gateway,
        ChatResult(
            content="",
            model="scripted",
            tool_calls=(ToolCall(name="submit_understanding", arguments=args),),
        ),
    )

    events = await post_sse(api, RUNS, {"message": "建 G9"})

    assert chat.options[0]["tools"][0]["function"]["name"] == "submit_understanding"
    assert of(events, "stage")[1]["detail"]["mode"] == "tools"
    run_id = of(events, "run")[0]["run_id"]
    async with create_session_factory(engine)() as s:
        row = await s.get(AgentRun, run_id)
        assert row is not None
        assert (row.status, row.understand_mode, row.risk) == ("awaiting_approval", "tools", "low")
        assert row.steps == [{"tool": "create_group", "args": {"name": "G9"}}]
        assert row.events[0]["type"] == "run" and row.events[-1]["type"] == "done"


async def test_runs_are_listed_replayable_and_cancellable(
    api: httpx.AsyncClient, llm_gateway: LLMGateway
) -> None:
    await login(api)
    script(llm_gateway, understood({"type": "create_group", "slots": {"name": "G10"}}))
    run_id = of(await post_sse(api, RUNS, {"message": "建 G10"}), "run")[0]["run_id"]

    listed = (await api.get(RUNS, headers=ALICE)).json()
    assert listed["total"] == 1 and listed["items"][0]["status"] == "awaiting_approval"
    detail = (await api.get(f"{RUNS}/{run_id}", headers=ALICE)).json()
    assert [e["type"] for e in detail["events"]][:2] == ["run", "stage"]
    assert (await api.get(f"{RUNS}/nope", headers=ALICE)).status_code == 404

    assert (await api.delete(f"{RUNS}/{run_id}", headers=ALICE)).status_code == 204
    out = await post_sse(api, f"{RUNS}/{run_id}/execute", {})
    assert of(out, "error")[0]["reason"] == "plan_expired"
    assert (await api.get(f"{RUNS}/{run_id}", headers=ALICE)).json()["status"] == "cancelled"


def test_eval_cases_are_valid_and_scored_strictly() -> None:
    from app.services.admin_agent.evaluate import load_cases, score
    from app.services.admin_agent.tasks import TASKS

    cases = load_cases()
    assert {c["lang"] for c in cases} == {"zh", "en", "vi"}
    assert len({c["id"] for c in cases}) == len(cases) >= 45
    for case in cases:
        for task in case["expect"]["tasks"]:
            assert task["type"] in TASKS, case["id"]

    case = next(c for c in cases if c["id"] == "zh-onboard-missing-username")
    good = {
        "intent": "change",
        "tasks": [{"type": "onboard_user", "slots": {"display_name": "王芳"}}],
    }
    assert score(case, good).passed
    invented = {
        "intent": "change",
        "tasks": [
            {"type": "onboard_user", "slots": {"display_name": "王芳", "username": "wangfang"}}
        ],
    }
    result = score(case, invented)
    assert not result.passed and result.invented == ["onboard_user.username"]

    full = next(c for c in cases if c["id"] == "en-onboard-full")
    split: dict[str, Any] = {
        "intent": "change",
        "tasks": [
            {
                "type": "onboard_user",
                "slots": {
                    "username": "hien",
                    "display_name": "Nguyen Minh Hien",
                    "employee_no": "26003932",
                },
            },
            {"type": "add_to_group", "slots": {"group": "ERP Team", "users": ["hien"]}},
            {"type": "assign_roles", "slots": {"roles": ["kb_editor"], "users": ["hien"]}},
        ],
    }
    assert score(full, split).passed
    split["tasks"][1]["slots"]["users"] = ["hien", "someone"]
    assert not score(full, split).passed

    zh_full = next(c for c in cases if c["id"] == "zh-onboard-full")
    zh_slots = {
        "username": "hien",
        "display_name": "Nguyen Minh Hien",
        "employee_no": "26003932",
        "department": "IT 运维部",
        "groups": ["ERP 项目组"],
        "roles": ["知识库编辑者"],
    }
    grant = {
        "type": "grant_kb_access",
        "slots": {
            "knowledge_base": "特种面料厂IT运维知识库",
            "grants": [{"principal_type": "user", "principal": "hien", "permission": "edit"}],
        },
    }
    separate = {"intent": "change", "tasks": [{"type": "onboard_user", "slots": zh_slots}, grant]}
    assert score(zh_full, separate).passed
    inline = {
        "intent": "change",
        "tasks": [
            {
                "type": "onboard_user",
                "slots": {
                    **zh_slots,
                    "kb_grants": [
                        {"knowledge_base": "特种面料厂IT运维知识库", "permission": "edit"}
                    ],
                },
            }
        ],
    }
    assert score(zh_full, inline).passed


def test_temporary_passwords_are_never_persisted() -> None:
    from app.services.admin_agent.service import Event, storable

    event = Event(
        "step",
        {
            "index": 0,
            "status": "done",
            "output": {"user": "x", "temporary_password": "S3cret12abcd"},
        },
    )
    stored = storable(event)
    assert stored["data"]["output"] == {"user": "x", "temporary_password": "***"}
    assert "S3cret12abcd" not in json.dumps(stored)


def test_equivalent_slot_shapes_are_normalized_by_code() -> None:
    from app.services.admin_agent.tasks import TASKS

    grant = TASKS["grant_kb_access"].slots.model_validate(
        {"knowledge_base": "K", "principal_type": "dept", "principal": "IT", "permission": "read"}
    )
    assert grant.model_dump()["grants"] == [
        {"principal_type": "dept", "principal": "IT", "permission": "read"}
    ]
    members = TASKS["add_to_group"].slots.model_validate({"group": "G", "user": "xiaoli"})
    assert members.model_dump()["users"] == ["xiaoli"]
    roles = TASKS["assign_roles"].slots.model_validate({"user": "a", "role": "kb_editor"})
    assert roles.model_dump()["roles"] == ["kb_editor"]


async def test_only_admins_may_use_the_assistant(api: httpx.AsyncClient) -> None:
    await login(api)
    for headers in (BOB, CAROL):
        resp = await api.post(RUNS, json={"message": "hi"}, headers=headers)
        assert resp.status_code == 403


async def test_grant_ignores_grants_of_deleted_principals(
    api: httpx.AsyncClient, engine: AsyncEngine, llm_gateway: LLMGateway
) -> None:
    await login(api)
    kb = (
        await api.post(
            "/api/v1/knowledge-bases",
            json={"name": "旧库", "visibility": "restricted"},
            headers=ALICE,
        )
    ).json()
    async with create_session_factory(engine)() as s:
        alice = (await s.execute(select(User).where(User.username == "alice"))).scalar_one()
        s.add(
            ResourceAcl(
                org_id=alice.org_id,
                resource_type="kb",
                resource_id=kb["id"],
                principal_type="dept",
                principal_id="gone-dept",
                permission="read",
            )
        )
        await s.commit()
    grant = {"principal_type": "user", "principal": "carol", "permission": "edit"}
    script(
        llm_gateway,
        understood(
            {"type": "grant_kb_access", "slots": {"knowledge_base": "旧库", "grants": [grant]}}
        ),
    )
    plan = of(await post_sse(api, RUNS, {"message": "让 carol 编辑旧库"}), "plan")[0]
    assert plan["steps"][0]["warnings"] == [{"code": "stale_grants", "count": "1"}]

    out = await post_sse(api, f"{RUNS}/{plan['run_id']}/execute", {})

    assert of(out, "report")[-1]["outcome"] == "done"
    async with create_session_factory(engine)() as s:
        rows = (
            await s.execute(
                select(ResourceAcl.principal_type, ResourceAcl.permission).where(
                    ResourceAcl.resource_id == kb["id"]
                )
            )
        ).all()
        assert sorted(rows) == [("user", "edit"), ("user", "manage")]
        assert (
            await s.execute(select(KnowledgeBase).where(KnowledgeBase.name == "旧库"))
        ).scalar_one()
