"""Static guards for high-blast-radius worker correctness contracts.

These tests intentionally avoid importing ``modal_app`` because importing it
constructs Modal images and requires dependencies that are irrelevant to the
contracts under test.
"""

from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"
SOURCE = MODAL_APP.read_text()
TREE = ast.parse(SOURCE)


def _function_source(name: str) -> str:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            lines = SOURCE.splitlines()
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"function not found: {name}")


def test_retention_never_truncates_or_deletes_canonical_history() -> None:
    """Stack/market/regime history feeds VLSTM, MRS, backtests, and dashboard."""

    destructive_fragments = [
        "truncate table stack_curves",
        "truncate table stack_clearing_prices",
        "delete from stack_curves",
        "delete from stack_clearing_prices",
        "delete from jepx_spot_prices",
        "delete from demand_actuals",
        "delete from generation_mix_actuals",
        "delete from weather_obs",
        "delete from regime_states",
    ]
    lower_source = SOURCE.lower()

    for fragment in destructive_fragments:
        assert fragment not in lower_source


def test_legacy_prune_entrypoint_routes_to_forecast_path_pruner() -> None:
    prune_old_data = _function_source("prune_old_data").lower()

    assert "prune_forecast_paths.local" in prune_old_data
    assert "delete from" not in prune_old_data
    assert "truncate table" not in prune_old_data


def test_forecast_pruner_preserves_runs_and_inflight_valuation_paths() -> None:
    prune_forecast_paths = _function_source("prune_forecast_paths").lower()

    assert "delete from forecast_paths" in prune_forecast_paths
    assert "delete from forecast_runs" not in prune_forecast_paths
    assert "status in ('queued', 'running')" in prune_forecast_paths
