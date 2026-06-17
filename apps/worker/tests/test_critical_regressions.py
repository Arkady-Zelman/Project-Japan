from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"


def _function_source(name: str) -> str:
    source = MODAL_APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function not found: {name}")


def test_nightly_retention_preserves_canonical_history_tables() -> None:
    """Canonical history is an input, not cache; scheduled retention must not delete it."""
    prune_old_data = _function_source("prune_old_data").lower()
    canonical_tables = (
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "stack_curves",
        "stack_clearing_prices",
        "regime_states",
    )

    assert "truncate" not in prune_old_data
    for table in canonical_tables:
        assert f"delete from {table}" not in prune_old_data


def test_nightly_retention_prunes_forecast_paths_instead() -> None:
    """The generated forecast-path table is the bounded high-volume table."""
    prune_old_data = _function_source("prune_old_data")
    prune_nightly = _function_source("prune_nightly")

    assert "prune_forecast_paths.local" in prune_old_data
    assert "prune_old_data.local" in prune_nightly
