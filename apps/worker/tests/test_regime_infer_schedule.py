from __future__ import annotations

import ast
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]


def _module(relative: str) -> ast.Module:
    return ast.parse((WORKER_ROOT / relative).read_text())


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def test_daily_regime_infer_uses_window_large_enough_for_mrs_fit() -> None:
    fn = _function(_module("modal_app.py"), "regime_infer_daily")
    timedelta_days = [
        kw.value.value
        for call in ast.walk(fn)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "timedelta"
        for kw in call.keywords
        if kw.arg == "days" and isinstance(kw.value, ast.Constant)
    ]

    assert 14 in timedelta_days
    assert 1 in timedelta_days


def test_regime_infer_precheck_matches_jw_mrs_minimum() -> None:
    tree = _module("regime/infer_state.py")
    module_constants = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }

    assert module_constants["_MIN_INFER_RESIDUALS"] == 200

    fn = _function(tree, "infer_area")
    comparisons = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, ast.Lt) for op in node.ops)
        and any(
            isinstance(comparator, ast.Name) and comparator.id == "_MIN_INFER_RESIDUALS"
            for comparator in node.comparators
        )
    ]
    assert comparisons
