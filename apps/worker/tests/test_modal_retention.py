"""Static guards for Modal retention entry points.

These tests deliberately avoid importing modal_app.py because Modal decorators
need the Modal package/runtime. The retention contract is still important
enough to lock down: scheduled cleanup may prune generated forecast artifacts,
but must never delete canonical historical market inputs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


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


def _function_source(function_name: str) -> str:
    source = MODAL_APP.read_text()
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"{function_name} not found in {MODAL_APP}")


@pytest.mark.parametrize("function_name", ["prune_old_data", "prune_nightly"])
def test_retention_entrypoints_only_prune_forecast_artifacts(function_name: str) -> None:
    source = _function_source(function_name)
    lowered = source.lower()

    assert "prune_forecast_paths.local(retain_latest_per_area=2)" in source
    assert "delete from" not in lowered
    assert "truncate" not in lowered
    for table in CANONICAL_HISTORY_TABLES:
        assert table not in lowered


def test_stack_daily_spawns_safe_nightly_retention_entrypoint() -> None:
    source = _function_source("stack_run_daily")

    assert "prune_nightly.spawn()" in source
    assert "prune_old_data" not in source
