"""Static guards for high-severity correctness contracts.

These tests deliberately avoid importing ``modal_app`` because that would pull
Modal and the full worker dependency graph into the test process. The contracts
below protect destructive data-retention paths, so source-level assertions are
an appropriate tripwire.
"""

from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"

CANONICAL_HISTORY_TABLES = {
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
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{name} not found in {MODAL_APP}")


def _normalise_sql(source: str) -> str:
    return " ".join(source.lower().split())


def test_nightly_retention_does_not_delete_canonical_history_tables() -> None:
    """Canonical market/fundamental history must never be nightly-pruned."""

    retention_source = "\n".join(
        [
            _function_source("prune_old_data"),
            _function_source("prune_nightly"),
            _function_source("stack_run_daily"),
        ]
    )
    normalised = _normalise_sql(retention_source)

    assert "truncate table" not in normalised
    for table in CANONICAL_HISTORY_TABLES:
        assert f"delete from {table}" not in normalised


def test_forecast_retention_preserves_parent_runs_and_inflight_valuations() -> None:
    """Only heavy forecast_paths rows are pruned; forecast_runs provenance stays."""

    source = _normalise_sql(_function_source("prune_forecast_paths"))

    assert "delete from forecast_paths" in source
    assert "delete from forecast_runs" not in source
    assert "truncate table forecast_runs" not in source
    assert "from valuations" in source
    assert "status in ('queued', 'running')" in source

