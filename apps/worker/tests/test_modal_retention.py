from __future__ import annotations

import ast
from pathlib import Path


_MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"


def _function_source(function_name: str) -> str:
    tree = ast.parse(_MODAL_APP.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.unparse(node)
    raise AssertionError(f"function not found: {function_name}")


def test_nightly_retention_only_prunes_generated_forecasts() -> None:
    """Nightly retention must not delete canonical market/fundamental history."""
    source = _function_source("prune_nightly")

    assert "prune_forecast_paths" in source
    assert "prune_old_data" not in source

    forbidden_tables = {
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "stack_curves",
        "stack_clearing_prices",
        "regime_states",
    }
    for table in forbidden_tables:
        assert table not in source


def test_emergency_historical_prune_requires_explicit_confirmation() -> None:
    source = _function_source("prune_old_data")

    assert "confirm_destructive" in source
    assert "destructive historical-data prune requires" in source
