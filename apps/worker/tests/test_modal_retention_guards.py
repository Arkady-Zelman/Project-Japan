"""Regression guards for Modal retention jobs.

These tests intentionally inspect source text instead of importing
``modal_app``: importing it requires Modal's runtime package and constructs a
cloud image. The retention bug was a destructive SQL change, so static checks
provide a cheap guard against reintroducing the dangerous statements.
"""

from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"


PROTECTED_TABLES = {
    "jepx_spot_prices",
    "demand_actuals",
    "generation_mix_actuals",
    "weather_obs",
    "stack_curves",
    "stack_clearing_prices",
    "regime_states",
}


def _function_string_literals(function_name: str) -> list[str]:
    module = ast.parse(MODAL_APP.read_text())
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return [
                child.value.lower()
                for child in ast.walk(node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            ]
    raise AssertionError(f"function not found: {function_name}")


def test_retention_entrypoints_do_not_delete_canonical_history() -> None:
    literals = "\n".join(
        _function_string_literals("_prune_forecast_paths_impl")
        + _function_string_literals("prune_forecast_paths")
        + _function_string_literals("prune_old_data")
        + _function_string_literals("prune_nightly")
    )

    assert "truncate" not in literals
    for table in PROTECTED_TABLES:
        assert f"delete from {table}" not in literals
        assert f"vacuum {table}" not in literals


def test_forecast_retention_preserves_run_metadata_and_inflight_inputs() -> None:
    literals = "\n".join(_function_string_literals("_prune_forecast_paths_impl"))

    assert "delete from forecast_paths" in literals
    assert "delete from forecast_runs" not in literals
    assert "v.forecast_run_id = r.id" in literals
    assert "v.status in ('queued', 'running')" in literals


def test_forecast_retention_uses_session_timeout_across_batch_commits() -> None:
    literals = "\n".join(_function_string_literals("_prune_forecast_paths_impl"))

    assert "set statement_timeout = '600s'" in literals
    assert "set local statement_timeout" not in literals
