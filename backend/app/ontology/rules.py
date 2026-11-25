"""Business rule evaluation for actions / state transitions (Wave C Task12)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.models.action import RuleVerdict


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    verdict: str
    rule_name: str | None = None
    message: str | None = None
    matched: bool = False


def _match_condition(condition: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    """Shallow match: every non-empty condition key must equal context value.

    Special keys:
      - action: must equal context['action']
      - when: nested dict matched against context['object'] (or top-level)
      - to: matched against context['to'] / context['to_status']
    """
    if not condition:
        return True
    action = condition.get("action")
    if action is not None and str(action) != str(context.get("action") or ""):
        return False
    to_val = condition.get("to")
    if to_val is not None:
        actual = context.get("to_status", context.get("to"))
        if str(to_val) != str(actual or ""):
            return False
    when = condition.get("when")
    if isinstance(when, Mapping):
        obj = context.get("object")
        base = obj if isinstance(obj, Mapping) else context
        for key, expected in when.items():
            if str(base.get(key) if isinstance(base, Mapping) else None) != str(expected):
                return False
    for key, expected in condition.items():
        if key in {"action", "when", "to"}:
            continue
        if str(context.get(key)) != str(expected):
            return False
    return True


def evaluate_rules(
    rules: Sequence[Any],
    context: Mapping[str, Any],
) -> RuleEvaluation:
    """Evaluate enabled rules by ascending priority; first match wins.

    ``rules`` items need ``.priority``, ``.enabled``, ``.condition``, ``.verdict``,
    ``.name``, ``.message`` (OntologyRule or SimpleNamespace).
    """
    ordered = sorted(
        (r for r in rules if getattr(r, "enabled", True)),
        key=lambda r: int(getattr(r, "priority", 100)),
    )
    for rule in ordered:
        cond = getattr(rule, "condition", None) or {}
        if not isinstance(cond, Mapping):
            continue
        if not _match_condition(cond, context):
            continue
        verdict = str(getattr(rule, "verdict", RuleVerdict.ALLOW.value))
        return RuleEvaluation(
            verdict=verdict,
            rule_name=str(getattr(rule, "name", "") or None),
            message=getattr(rule, "message", None),
            matched=True,
        )
    return RuleEvaluation(verdict=RuleVerdict.ALLOW.value, matched=False)
