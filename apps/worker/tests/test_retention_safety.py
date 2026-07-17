"""Regression guards for automated database retention.

These tests inspect the Modal entrypoint as text so they stay fast and do not
require importing Modal or connecting to Postgres.
"""

from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).parents[1] / "modal_app.py"
SOURCE = MODAL_APP.read_text()
TREE = ast.parse(SOURCE)


def _function_source(name: str) -> str:
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SOURCE, node) or ""
    raise AssertionError(f"{name} not found in {MODAL_APP}")


def test_scheduled_retention_never_deletes_canonical_history() -> None:
    lowered = SOURCE.lower()
    protected_tables = (
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "stack_curves",
        "stack_clearing_prices",
        "regime_states",
    )

    assert "truncate table" not in lowered
    for table in protected_tables:
        assert f"delete from {table}" not in lowered


def test_forecast_retention_preserves_parents_and_active_inputs() -> None:
    source = _function_source("prune_forecast_paths").lower()

    assert "delete from forecast_paths" in source
    assert "delete from forecast_runs" not in source
    assert "from valuations" in source
    assert "'queued'" in source
    assert "'running'" in source


def test_legacy_and_nightly_entrypoints_use_safe_path_retention() -> None:
    for name in ("prune_old_data", "prune_nightly"):
        source = _function_source(name)
        assert "prune_forecast_paths.local()" in source
