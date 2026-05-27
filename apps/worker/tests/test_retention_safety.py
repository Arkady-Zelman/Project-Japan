from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"
SOURCE = MODAL_APP.read_text()
TREE = ast.parse(SOURCE)


def _function_source(name: str) -> str:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            source = ast.get_source_segment(SOURCE, node)
            assert source is not None
            return source
    raise AssertionError(f"function not found: {name}")


def _function_def(name: str) -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function not found: {name}")


def test_nightly_retention_only_prunes_forecast_paths() -> None:
    source = _function_source("prune_nightly").lower()

    assert "prune_forecast_paths.local" in source
    for forbidden in [
        "prune_old_data",
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "regime_states",
        "stack_curves",
        "stack_clearing_prices",
        "truncate table",
    ]:
        assert forbidden not in source


def test_destructive_prune_requires_explicit_confirmation() -> None:
    function_def = _function_def("prune_old_data")
    arg_names = [arg.arg for arg in function_def.args.args]
    assert "confirm_destructive" in arg_names

    default_by_arg = dict(
        zip(arg_names[-len(function_def.args.defaults):], function_def.args.defaults, strict=True),
    )
    assert isinstance(default_by_arg["confirm_destructive"], ast.Constant)
    assert default_by_arg["confirm_destructive"].value is False

    source = _function_source("prune_old_data").lower()
    assert source.index("if not confirm_destructive") < source.index("truncate table")
