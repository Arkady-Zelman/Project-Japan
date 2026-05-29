"""Regression tests for Modal retention safety.

These tests intentionally inspect the source instead of importing modal_app:
the decorators require Modal at import time, but the failure mode we are
guarding is a scheduled call path pointing at destructive SQL.
"""

from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"
SOURCE = MODAL_APP.read_text()
TREE = ast.parse(SOURCE)


def _function_node(name: str) -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in modal_app.py")


def _function_source(name: str) -> str:
    node = _function_node(name)
    source = ast.get_source_segment(SOURCE, node)
    assert source is not None
    return source


def test_prune_nightly_only_prunes_generated_forecasts() -> None:
    source = _function_source("prune_nightly")

    assert "prune_forecast_paths.local" in source
    assert "prune_old_data" not in source

    protected_tables = (
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "regime_states",
        "stack_curves",
        "stack_clearing_prices",
    )
    for table in protected_tables:
        assert table not in source


def test_stack_run_daily_does_not_schedule_destructive_prune() -> None:
    source = _function_source("stack_run_daily")

    assert "prune_nightly.spawn" in source
    assert "prune_old_data" not in source
    assert "TRUNCATE" not in source.upper()


def test_destructive_prune_requires_explicit_confirmation() -> None:
    node = _function_node("prune_old_data")
    source = _function_source("prune_old_data")

    arg_names = [arg.arg for arg in node.args.args]
    assert "confirm_destructive" in arg_names

    default_by_arg = dict(zip(arg_names[-len(node.args.defaults) :], node.args.defaults, strict=True))
    confirm_default = default_by_arg["confirm_destructive"]
    assert isinstance(confirm_default, ast.Constant)
    assert confirm_default.value is False

    guard_pos = source.index("if not confirm_destructive:")
    destructive_sql_pos = min(
        source.index('"jepx_spot_prices"'),
        source.index("truncate table stack_curves"),
    )
    assert guard_pos < destructive_sql_pos
