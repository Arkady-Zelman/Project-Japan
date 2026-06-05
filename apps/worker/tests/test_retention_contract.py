from __future__ import annotations

import ast
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "modal_app.py"


def _function_source(name: str) -> str:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"function not found: {name}")


def test_scheduled_retention_only_prunes_forecast_paths() -> None:
    source = _function_source("prune_nightly").lower()

    assert "prune_forecast_paths.local" in source
    assert "prune_old_data.local" not in source
    assert "delete from" not in source
    assert "truncate table" not in source


def test_prune_old_data_preserves_canonical_history_tables() -> None:
    source = _function_source("prune_old_data").lower()

    assert "prune_forecast_paths.local" in source
    assert "delete from" not in source
    assert "truncate table" not in source

    canonical_tables = {
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "stack_curves",
        "stack_clearing_prices",
        "regime_states",
    }
    for table in canonical_tables:
        assert table not in source
