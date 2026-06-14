from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"
PROTECTED_TABLES = {
    "jepx_spot_prices",
    "demand_actuals",
    "generation_mix_actuals",
    "weather_obs",
    "stack_curves",
    "stack_clearing_prices",
    "regime_states",
}


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(MODAL_APP.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _body_string_literals(fn: ast.FunctionDef) -> str:
    body = fn.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return "\n".join(
        node.value.lower()
        for stmt in body
        for node in ast.walk(stmt)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def test_nightly_retention_delegates_to_forecast_path_prune_only() -> None:
    fn = _function("prune_nightly")
    calls = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "local"
        and isinstance(node.func.value, ast.Name)
    ]

    assert [call.func.value.id for call in calls] == ["prune_forecast_paths"]
    assert calls[0].keywords[0].arg == "retain_latest_per_area"
    assert isinstance(calls[0].keywords[0].value, ast.Constant)
    assert calls[0].keywords[0].value.value == 2


def test_retention_wrappers_do_not_delete_canonical_tables() -> None:
    for name in ("prune_old_data", "prune_nightly"):
        sql_literals = _body_string_literals(_function(name))
        assert "truncate" not in sql_literals
        for table in PROTECTED_TABLES:
            assert f"delete from {table}" not in sql_literals
            assert f"vacuum {table}" not in sql_literals
