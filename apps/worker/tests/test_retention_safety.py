"""Regression guards for scheduled database retention.

These tests inspect source instead of importing ``modal_app`` so they run
without Modal credentials or the worker's production dependencies.
"""

from __future__ import annotations

import ast
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "modal_app.py"
SOURCE = MODULE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
LSM_RUNNER_SOURCE = (
    Path(__file__).parents[1] / "lsm/runner.py"
).read_text(encoding="utf-8").lower()


def _function_source(name: str) -> str:
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(SOURCE, node)
            assert segment is not None
            return segment
    raise AssertionError(f"function {name!r} not found")


def test_scheduled_retention_only_routes_to_forecast_path_pruning() -> None:
    for entrypoint in ("prune_old_data", "prune_nightly"):
        source = _function_source(entrypoint)
        assert "return _prune_forecast_paths()" in source


def test_retention_never_deletes_canonical_historical_tables() -> None:
    source = "\n".join(
        _function_source(name)
        for name in ("_prune_forecast_paths", "prune_old_data", "prune_nightly")
    ).lower()

    assert "truncate" not in source
    for table in (
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "stack_curves",
        "stack_clearing_prices",
        "regime_states",
    ):
        assert f"delete from {table}" not in source


def test_forecast_retention_preserves_run_metadata_and_active_inputs() -> None:
    source = _function_source("_prune_forecast_paths").lower()

    assert "delete from forecast_paths fp" in source
    assert "delete from forecast_runs" not in source
    # The active-valuation exclusion is checked when candidates are selected
    # and again atomically in each DELETE statement.
    assert source.count("from valuations") == 2
    assert source.count("v.status in ('queued', 'running')") == 2


def test_lsm_fails_closed_for_pruned_paths_and_duplicate_runs() -> None:
    assert "raise runtimeerror(" in LSM_RUNNER_SOURCE
    assert "incomplete forecast paths:" in LSM_RUNNER_SOURCE
    assert "expected queued" in LSM_RUNNER_SOURCE
    assert "and status in ('queued', 'running')" in LSM_RUNNER_SOURCE
