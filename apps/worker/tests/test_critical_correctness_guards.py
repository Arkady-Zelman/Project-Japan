from __future__ import annotations

import ast
from pathlib import Path


SOURCE_PATH = Path(__file__).resolve().parents[1] / "modal_app.py"


def _function_source(name: str) -> str:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"function {name!r} not found")


def test_retention_entrypoints_do_not_delete_canonical_history() -> None:
    prune_old_data = _function_source("prune_old_data").lower()
    prune_nightly = _function_source("prune_nightly").lower()

    assert "prune_forecast_paths.local()" in prune_old_data
    assert "prune_old_data.local()" in prune_nightly

    canonical_tables = [
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "regime_states",
        "stack_curves",
        "stack_clearing_prices",
    ]
    for table in canonical_tables:
        assert f"delete from {table}" not in prune_old_data
        assert f"truncate table {table}" not in prune_old_data

    assert "truncate table" not in prune_old_data


def test_forecast_path_pruner_preserves_runs_and_inflight_inputs() -> None:
    pruner = _function_source("prune_forecast_paths").lower()

    assert "delete from forecast_paths" in pruner
    assert "delete from forecast_runs" not in pruner
    assert "from valuations" in pruner
    assert "queued" in pruner
    assert "running" in pruner
