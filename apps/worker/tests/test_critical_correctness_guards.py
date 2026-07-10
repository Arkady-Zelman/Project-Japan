"""Static guards for production-data retention safety.

These tests intentionally inspect modal_app.py as text/AST instead of importing
it, because importing the Modal app requires the full Modal runtime. The goal is
to catch high-blast-radius retention regressions before deployment.
"""

from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"
SOURCE = MODAL_APP.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function_source(name: str) -> str:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(SOURCE, node)
            assert segment is not None
            return segment.lower()
    raise AssertionError(f"{name} not found in modal_app.py")


def test_prune_old_data_preserves_canonical_history_tables() -> None:
    """Nightly retention must not erase product history or model inputs."""

    source = _function_source("prune_old_data")
    forbidden_tables = [
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "stack_curves",
        "stack_clearing_prices",
        "regime_states",
    ]
    destructive_verbs = ["delete from", "truncate table"]

    for verb in destructive_verbs:
        for table in forbidden_tables:
            assert f"{verb} {table}" not in source

    assert "forecast_paths_only" in source
    assert "prune_forecast_paths.local()" in source


def test_forecast_retention_keeps_forecast_run_parents() -> None:
    """Valuations reference forecast_runs, so retention can only prune paths."""

    source = _function_source("prune_forecast_paths")

    assert "delete from forecast_paths" in source
    assert "delete from forecast_runs" not in source
    assert "active_valuations" in source
    assert "status in ('queued', 'running')" in source
    assert "forecast_runs_after" in source
