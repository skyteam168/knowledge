"""Safe attribute compute expressions: identifiers, numbers, + - * / ( )."""

from __future__ import annotations

import ast
import operator
import re
from typing import Any

from app.core.exceptions import ValidationAppError

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

_UNARY: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def validate_compute_expr(expr: str, *, inputs: list[str] | None = None) -> str:
    """Parse and validate; return normalized expression string."""
    text = (expr or "").strip()
    if not text:
        raise ValidationAppError("compute_expr required")
    if len(text) > 256:
        raise ValidationAppError("compute_expr too long")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValidationAppError(f"invalid compute_expr: {exc.msg}") from exc
    names = _collect_names(tree.body)
    for name in names:
        if not _IDENT.match(name) or name.startswith("__"):
            raise ValidationAppError(f"illegal identifier in compute_expr: {name}")
    if inputs is not None:
        allowed = {i.strip() for i in inputs if i.strip()}
        unknown = sorted(names - allowed)
        if unknown:
            raise ValidationAppError(
                "compute_expr references unknown inputs",
                detail={"unknown": unknown},
            )
    # Round-trip via AST to reject exotic nodes early
    _eval_node(tree.body, {n: 1.0 for n in names})
    return text


def eval_compute_expr(expr: str, attrs: dict[str, Any]) -> float | int:
    """Evaluate a validated expression against attribute values."""
    text = (expr or "").strip()
    if not text:
        raise ValidationAppError("compute_expr required")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValidationAppError(f"invalid compute_expr: {exc.msg}") from exc
    names = _collect_names(tree.body)
    values: dict[str, float] = {}
    for name in names:
        if name not in attrs:
            raise ValidationAppError(
                f"missing input for compute_expr: {name}",
                detail={"name": name},
            )
        raw = attrs[name]
        try:
            values[name] = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationAppError(
                f"non-numeric input for compute_expr: {name}",
                detail={"name": name},
            ) from exc
    result = _eval_node(tree.body, values)
    if isinstance(result, float) and result.is_integer():
        return int(result)
    return result


def _collect_names(node: ast.AST) -> set[str]:
    names: set[str] = set()

    def walk(n: ast.AST) -> None:
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Constant):
            if not isinstance(n.value, (int, float)):
                raise ValidationAppError("only numeric constants allowed")
        elif isinstance(n, ast.BinOp):
            if type(n.op) not in _BINOPS:
                raise ValidationAppError("unsupported operator")
            walk(n.left)
            walk(n.right)
        elif isinstance(n, ast.UnaryOp):
            if type(n.op) not in _UNARY:
                raise ValidationAppError("unsupported unary operator")
            walk(n.operand)
        elif isinstance(n, ast.Expression):
            walk(n.body)
        else:
            raise ValidationAppError(
                f"unsupported expression node: {type(n).__name__}"
            )

    walk(node)
    return names


def _eval_node(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return float(values[node.id])
    if isinstance(node, ast.UnaryOp):
        op = _UNARY[type(node.op)]
        return float(op(_eval_node(node.operand, values)))
    if isinstance(node, ast.BinOp):
        op = _BINOPS[type(node.op)]
        left = _eval_node(node.left, values)
        right = _eval_node(node.right, values)
        if isinstance(node.op, ast.Div) and right == 0:
            raise ValidationAppError("division by zero in compute_expr")
        return float(op(left, right))
    raise ValidationAppError(f"unsupported expression node: {type(node).__name__}")
