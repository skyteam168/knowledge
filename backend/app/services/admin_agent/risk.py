"""Rule-based risk of plan steps. High-risk plans need an explicit acknowledgement to run."""

from dataclasses import dataclass, field
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high"]
_RANK = {"low": 0, "medium": 1, "high": 2}
BULK_USERS = 20


@dataclass
class Risk:
    level: RiskLevel = "low"
    reasons: list[dict[str, str]] = field(default_factory=list)

    def raise_to(self, level: RiskLevel, code: str, **params: str) -> None:
        if _RANK[level] > _RANK[self.level]:
            self.level = level
        self.reasons.append({"code": code, "level": level, **params})


def assess_step(tool: str, args: dict[str, Any], warnings: list[dict[str, str]]) -> Risk:
    risk = Risk()
    users = args.get("users") or []
    if len(users) > BULK_USERS:
        risk.raise_to("high", "bulk_users", count=str(len(users)))
    if tool == "assign_roles" and any(w.get("code") == "privileged_role" for w in warnings):
        risk.raise_to("high", "privileged_role")
    if tool == "grant_kb_access":
        if args.get("permission") == "manage":
            risk.raise_to("medium", "grant_manage")
        if args.get("principal_type") in ("dept", "role"):
            risk.raise_to("medium", "broad_grant")
    if tool == "set_kb_visibility" and args.get("visibility") == "org":
        risk.raise_to("medium", "org_visible")
    if tool == "open_password_login":
        risk.raise_to("medium", "credentials")
    codes = {w.get("code") for w in warnings}
    if tool == "revoke_kb_access" and "self_manage_revoke" in codes:
        risk.raise_to("high", "self_manage_revoke")
    if tool == "remove_roles" and "self_privilege_removal" in codes:
        risk.raise_to("high", "self_privilege_removal")
    if tool == "disable_users":
        risk.raise_to("medium", "disable_users", count=str(len(users)))
    if tool == "move_department" and "dept_move_users" in codes:
        risk.raise_to("medium", "dept_move")
    if tool == "set_role_permissions":
        affected = next((w["count"] for w in warnings if w.get("code") == "role_users"), "0")
        risk.raise_to("high" if affected != "0" else "medium", "role_permissions", count=affected)
    if tool in ("create_role", "set_role_permissions") and "privileged_permission" in codes:
        risk.raise_to("high", "privileged_permission")
    if tool == "start_eval_run" and "judge_cost" in codes:
        risk.raise_to("medium", "judge_cost")
    return risk


def overall(levels: list[RiskLevel]) -> RiskLevel:
    return max(levels, key=lambda lv: _RANK[lv], default="low")
