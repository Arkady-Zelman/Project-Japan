"""Static guards for high-severity worker correctness regressions.

These tests intentionally parse source text instead of importing modal_app:
cloud validation environments do not always have Modal installed locally, and
the retention contract is simple enough to guard statically.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODAL_APP = ROOT / "modal_app.py"
SOURCE = MODAL_APP.read_text(encoding="utf-8")
LINES = SOURCE.splitlines()
TREE = ast.parse(SOURCE)


def _function_source(name: str) -> str:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(LINES[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{name} not found in modal_app.py")


def test_nightly_retention_does_not_delete_canonical_history() -> None:
    retention_sources = "\n".join(
        _function_source(name)
        for name in (
            "_prune_forecast_paths_impl",
            "prune_forecast_paths",
            "prune_old_data",
            "prune_nightly",
        )
    ).lower()

    forbidden_fragments = [
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
    for fragment in forbidden_fragments:
        assert fragment not in retention_sources


def test_forecast_retention_preserves_run_metadata() -> None:
    retention_sources = "\n".join(
        _function_source(name)
        for name in ("_prune_forecast_paths_impl", "prune_forecast_paths")
    ).lower()

    assert "delete from forecast_paths" in retention_sources
    assert "delete from forecast_runs" not in retention_sources
    assert "truncate table forecast_runs" not in retention_sources


def test_forecast_retention_protects_in_flight_valuations() -> None:
    retention_source = _function_source("_prune_forecast_paths_impl").lower()

    assert "active_valuation_runs" in retention_source
    assert "status in ('queued', 'running')" in retention_source
    assert "active.id is null" in retention_source
