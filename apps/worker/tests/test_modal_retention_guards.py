"""Static guards for Modal retention safety.

These tests intentionally inspect source instead of importing modal_app: importing
that module requires Modal and builds the deployment image. The retention contract
is simple enough to guard statically.
"""

from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"
SOURCE = MODAL_APP.read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    tree = ast.parse(SOURCE)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(SOURCE, node)
            if segment is None:
                raise AssertionError(f"could not extract source for {name}")
            return segment
    raise AssertionError(f"function {name} not found")


def test_prune_old_data_does_not_mutate_canonical_history_tables() -> None:
    body = _function_source("prune_old_data").lower()

    assert "_prune_forecast_paths_impl" in body
    assert "canonical_history_pruned" in body
    assert "truncate" not in body
    assert "delete from" not in body
    for table in (
        "stack_curves",
        "stack_clearing_prices",
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "regime_states",
    ):
        assert table not in body


def test_forecast_retention_preserves_parent_runs_and_active_valuation_inputs() -> None:
    body = _function_source("_prune_forecast_paths_impl").lower()
    normalized = " ".join(body.split())

    assert "delete from forecast_paths" in body
    assert "delete from forecast_runs" not in body
    assert "from valuations" in body
    assert "v.status in ('queued', 'running')" in normalized
