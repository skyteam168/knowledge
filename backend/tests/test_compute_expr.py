"""Safe compute_expr evaluator."""

from __future__ import annotations

import pytest

from app.core.exceptions import ValidationAppError
from app.services.ontology_studio.compute import eval_compute_expr, validate_compute_expr


def test_eval_add() -> None:
    assert eval_compute_expr("a+b", {"a": 1, "b": 2}) == 3


def test_eval_complex() -> None:
    assert eval_compute_expr("(a+b)*c/2", {"a": 1, "b": 3, "c": 4}) == 8


def test_reject_import() -> None:
    with pytest.raises(ValidationAppError):
        validate_compute_expr("__import__('os').system('x')")


def test_reject_attr_access() -> None:
    with pytest.raises(ValidationAppError):
        validate_compute_expr("a.__class__")


def test_reject_call() -> None:
    with pytest.raises(ValidationAppError):
        validate_compute_expr("abs(a)")


def test_missing_input() -> None:
    with pytest.raises(ValidationAppError):
        eval_compute_expr("a+b", {"a": 1})
