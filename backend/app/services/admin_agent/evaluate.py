"""Offline evaluation of the understanding stage over a multilingual instruction set.

Only `understand` is evaluated: everything after it is deterministic code covered by unit tests.
A case passes when the intent is accepted, the task types match, every expected slot value is
present and every slot that must stay empty (information the admin did not give) is absent.
"""

import json
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.exceptions import AppError
from app.llm import ChatMessage, LLMGateway
from app.services.admin_agent.tasks import TASKS
from app.services.admin_agent.understand import understand

CASES_FILE = Path(__file__).with_name("eval_cases.json")


_TODAY = re.compile(r"@today(?:-(\d+))?")


def _dates(value: Any, today: date) -> Any:
    """`@today` / `@today-N` in expected values become ISO dates relative to `today`."""
    if isinstance(value, str):
        return _TODAY.sub(
            lambda m: (today - timedelta(days=int(m.group(1) or 0))).isoformat(), value
        )
    if isinstance(value, list):
        return [_dates(v, today) for v in value]
    if isinstance(value, dict):
        return {k: _dates(v, today) for k, v in value.items()}
    return value


def load_cases(path: Path = CASES_FILE, today: date | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return [_dates(c, today or date.today()) for c in cases]


def _value_ok(expected: Any, actual: Any) -> bool:
    """`a|b` alternatives for strings; lists match as sets; dicts match on expected keys."""
    if isinstance(expected, str):
        return isinstance(actual, str) and actual.strip().lower() in {
            alt.strip().lower() for alt in expected.split("|")
        }
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        remaining = list(actual)
        for item in expected:
            match = next((a for a in remaining if _value_ok(item, a)), None)
            if match is None:
                return False
            remaining.remove(match)
        return True
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            _value_ok(v, actual.get(k)) for k, v in expected.items()
        )
    return bool(expected == actual)


@dataclass
class CaseResult:
    id: str
    lang: str
    passed: bool
    intent_ok: bool
    tasks_ok: bool
    slots_expected: int
    slots_matched: int
    invented: list[str] = field(default_factory=list)
    mode: str | None = None
    latency_ms: int = 0
    error: str | None = None
    got: dict[str, Any] | None = None


def _only_user(slots: dict[str, Any], username: str) -> bool:
    users = slots.get("users")
    users = [users] if isinstance(users, str) else users
    return isinstance(users, list) and len(users) == 1 and str(users[0]).strip().lower() == username


def _user_grants(slots: dict[str, Any], username: str) -> list[dict[str, Any]] | None:
    grants = slots.get("grants")
    if not slots.get("knowledge_base") or not isinstance(grants, list) or not grants:
        return None
    if not all(
        isinstance(g, dict)
        and g.get("principal_type", "user") == "user"
        and str(g.get("principal", "")).strip().lower() == username
        for g in grants
    ):
        return None
    return [
        {"knowledge_base": slots["knowledge_base"], "permission": g.get("permission")}
        for g in grants
    ]


def _fold_onboarding(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`onboard_user` + `add_to_group` / `assign_roles` / `grant_kb_access` for that same new user
    is the same plan as `onboard_user` with `groups` / `roles` / `kb_grants` (the resolver accepts
    users planned earlier)."""
    out = [dict(t, slots=dict(t.get("slots") or {})) for t in tasks]
    for onboard in [t for t in out if t.get("type") == "onboard_user"]:
        username = str(onboard["slots"].get("username") or "").strip().lower()
        if not username:
            continue
        for task in list(out):
            slots = task["slots"]
            if (
                task.get("type") == "add_to_group"
                and slots.get("group")
                and _only_user(slots, username)
            ):
                onboard["slots"]["groups"] = [*onboard["slots"].get("groups", []), slots["group"]]
                out.remove(task)
            elif task.get("type") == "assign_roles" and _only_user(slots, username):
                roles = slots.get("roles") or []
                roles = [roles] if isinstance(roles, str) else roles
                onboard["slots"]["roles"] = [*onboard["slots"].get("roles", []), *roles]
                out.remove(task)
            elif task.get("type") == "grant_kb_access" and (
                grants := _user_grants(slots, username)
            ):
                onboard["slots"]["kb_grants"] = [*onboard["slots"].get("kb_grants", []), *grants]
                out.remove(task)
    return out


def _normalized(task: dict[str, Any]) -> dict[str, Any]:
    """Slots as the workflow uses them (shape normalization by the task's slot model)."""
    spec = TASKS.get(str(task.get("type")))
    if spec is None:
        return task
    try:
        slots = spec.slots.model_validate(task.get("slots") or {})
    except ValidationError:
        return task
    return {**task, "slots": slots.model_dump(mode="json", exclude_unset=True)}


def score(case: dict[str, Any], got: dict[str, Any]) -> CaseResult:
    expect = case["expect"]
    allow_extra = set(expect.get("allow_extra", []))
    tasks = [_normalized(t) for t in got.get("tasks", [])]
    got_tasks = [t for t in _fold_onboarding(tasks) if t.get("type") not in allow_extra]
    intent_ok = got.get("intent") in expect["intent"]
    tasks_ok = [t["type"] for t in expect["tasks"]] == [t.get("type") for t in got_tasks] or sorted(
        t["type"] for t in expect["tasks"]
    ) == sorted(str(t.get("type")) for t in got_tasks)
    expected_n = matched = 0
    invented: list[str] = []
    for exp in expect["tasks"]:
        actual: dict[str, Any] = next((t for t in got_tasks if t.get("type") == exp["type"]), {})
        slots = actual.get("slots") or {}
        for key, value in exp.get("slots", {}).items():
            expected_n += 1
            matched += int(_value_ok(value, slots.get(key)))
        invented += [f"{exp['type']}.{k}" for k in exp.get("absent", []) if slots.get(k)]
    passed = intent_ok and tasks_ok and matched == expected_n and not invented
    return CaseResult(
        id=case["id"],
        lang=case["lang"],
        passed=passed,
        intent_ok=intent_ok,
        tasks_ok=tasks_ok,
        slots_expected=expected_n,
        slots_matched=matched,
        invented=invented,
        got=got,
    )


async def run_case(
    gateway: LLMGateway, case: dict[str, Any], native_tools: bool, today: date | None = None
) -> CaseResult:
    history = [ChatMessage(m["role"], m["content"]) for m in case.get("history", [])]
    start = time.perf_counter()
    try:
        result = await understand(
            gateway, history, case["message"], native_tools=native_tools, today=today
        )
    except AppError as exc:
        return CaseResult(
            id=case["id"],
            lang=case["lang"],
            passed=False,
            intent_ok=False,
            tasks_ok=False,
            slots_expected=0,
            slots_matched=0,
            error=exc.message,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
    scored = score(case, result.understanding.model_dump())
    scored.mode = result.mode
    scored.latency_ms = int((time.perf_counter() - start) * 1000)
    return scored


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    by_lang: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_lang[r.lang].append(r)
        by_lang["all"].append(r)

    def stats(rows: list[CaseResult]) -> dict[str, Any]:
        n = len(rows)
        slots_expected = sum(r.slots_expected for r in rows)
        return {
            "cases": n,
            "pass_rate": round(sum(r.passed for r in rows) / n, 3) if n else None,
            "intent_accuracy": round(sum(r.intent_ok for r in rows) / n, 3) if n else None,
            "task_accuracy": round(sum(r.tasks_ok for r in rows) / n, 3) if n else None,
            "slot_accuracy": round(sum(r.slots_matched for r in rows) / slots_expected, 3)
            if slots_expected
            else None,
            "invented_values": sum(len(r.invented) for r in rows),
            "errors": sum(1 for r in rows if r.error),
            "native_tool_calls": sum(1 for r in rows if r.mode == "tools"),
            "avg_latency_ms": int(sum(r.latency_ms for r in rows) / n) if n else None,
        }

    return {
        "summary": {lang: stats(rows) for lang, rows in sorted(by_lang.items())},
        "failures": [asdict(r) for r in results if not r.passed],
    }
