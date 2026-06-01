"""Static guards for high-impact production regressions."""

from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"
PROTECTED_HISTORY_TABLES = {
    "jepx_spot_prices",
    "demand_actuals",
    "generation_mix_actuals",
    "weather_obs",
    "stack_curves",
    "stack_clearing_prices",
    "regime_states",
}


def _function_source(name: str) -> str:
    source = MODAL_APP.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"function {name!r} not found in modal_app.py")


def test_nightly_retention_does_not_delete_canonical_history() -> None:
    """The scheduled retention job must not prune canonical training/backtest data."""
    retention_source = "\n".join(
        [_function_source("prune_old_data"), _function_source("prune_nightly")]
    ).lower()

    protected_mentions = sorted(
        table for table in PROTECTED_HISTORY_TABLES if table in retention_source
    )
    assert protected_mentions == []
    assert "delete from" not in retention_source
    assert "truncate table" not in retention_source


def test_nightly_retention_uses_forecast_path_pruner() -> None:
    """Forecast path rows are generated and bulky, so they are safe to rotate."""
    nightly_source = _function_source("prune_nightly")
    assert "prune_forecast_paths.local(retain_latest_per_area=2)" in nightly_source
