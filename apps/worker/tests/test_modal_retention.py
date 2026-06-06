"""Regression guards for Modal retention wiring.

The Modal app itself requires production secrets/DB access, so these tests
inspect the source and ensure scheduled retention cannot prune canonical data.
"""

from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"
CANONICAL_TABLES = {
    "jepx_spot_prices",
    "demand_actuals",
    "generation_mix_actuals",
    "weather_obs",
    "regime_states",
    "stack_curves",
    "stack_clearing_prices",
}


def _function_source(name: str) -> str:
    source = MODAL_APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Function {name} not found in {MODAL_APP}")


def _string_constants(source: str) -> set[str]:
    return {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_prune_old_data_only_delegates_to_forecast_retention() -> None:
    source = _function_source("prune_old_data")
    constants = _string_constants(source)

    assert "prune_forecast_paths.local" in source
    assert "delete from" not in source.lower()
    assert "truncate table" not in source.lower()
    assert CANONICAL_TABLES.isdisjoint(constants)


def test_prune_nightly_uses_forecast_retention_directly() -> None:
    source = _function_source("prune_nightly")

    assert "prune_forecast_paths.local" in source
    assert "prune_old_data.local" not in source
