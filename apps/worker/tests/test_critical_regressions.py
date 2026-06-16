"""Static guards for recent high-severity worker regressions."""

from __future__ import annotations

import ast
from pathlib import Path

MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"

PROTECTED_CANONICAL_TABLES = {
    "jepx_spot_prices",
    "demand_actuals",
    "generation_mix_actuals",
    "weather_obs",
    "stack_curves",
    "stack_clearing_prices",
    "regime_states",
}


def _modal_app_tree() -> tuple[str, ast.Module]:
    source = MODAL_APP.read_text()
    return source, ast.parse(source)


def _function_source(name: str) -> str:
    source, tree = _modal_app_tree()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"function not found: {name}")


def test_nightly_retention_delegates_to_forecast_path_retention_only() -> None:
    """Nightly retention must not delete canonical historical product data."""
    prune_old_data_source = _function_source("prune_old_data")
    prune_nightly_source = _function_source("prune_nightly")

    assert "return prune_forecast_paths.local(retain_latest_per_area=2)" in prune_old_data_source
    assert "return prune_old_data.local()" in prune_nightly_source

    lower = prune_old_data_source.lower()
    assert "truncate table" not in lower
    assert "delete from" not in lower
    for table in PROTECTED_CANONICAL_TABLES:
        assert table not in lower


def test_forecast_path_retention_never_targets_canonical_tables() -> None:
    """The only scheduled retention target should be generated forecasts."""
    source = _function_source("prune_forecast_paths").lower()

    assert "delete from forecast_runs" in source
    assert "vacuum forecast_paths" in source
    assert "vacuum forecast_runs" in source

    for table in PROTECTED_CANONICAL_TABLES:
        assert table not in source
