"""Static guards for Modal retention jobs.

These tests intentionally avoid importing modal_app because the Modal SDK may
not be installed in lightweight validation environments.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODAL_APP = ROOT / "apps" / "worker" / "modal_app.py"
SOURCE = MODAL_APP.read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    tree = ast.parse(SOURCE)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            assert node.end_lineno is not None
            lines = SOURCE.splitlines()
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError(f"function {name!r} not found")


def _retention_source() -> str:
    return "\n\n".join(
        _function_source(name)
        for name in (
            "_prune_forecast_paths_impl",
            "prune_forecast_paths",
            "prune_old_data",
            "prune_nightly",
        )
    ).lower()


def test_retention_does_not_delete_canonical_history_tables() -> None:
    src = _retention_source()

    assert "truncate table" not in src
    assert "delete from forecast_paths" in src
    assert "delete from forecast_runs" not in src

    canonical_tables = (
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "stack_curves",
        "stack_clearing_prices",
        "regime_states",
    )
    for table in canonical_tables:
        assert f"delete from {table}" not in src


def test_forecast_path_prune_preserves_active_valuation_inputs() -> None:
    src = _function_source("_prune_forecast_paths_impl").lower()

    assert "status in ('queued', 'running')" in src
    assert "v.forecast_run_id = r.id" in src
    assert "forecast_runs_preserved" in src
