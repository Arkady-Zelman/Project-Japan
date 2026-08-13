"""Static guards for Modal retention safety.

These tests intentionally avoid importing modal_app.py because the Modal SDK is
not always installed in lightweight CI images. The retention bug class is
destructive SQL in scheduled cleanup, so source-level assertions are sufficient.
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
            return "\n".join(SOURCE.splitlines()[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"function {name!r} not found")


def test_scheduled_retention_does_not_delete_canonical_tables() -> None:
    scheduled_retention = "\n".join(
        [
            _function_source("prune_old_data"),
            _function_source("prune_nightly"),
        ]
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
        assert fragment not in scheduled_retention


def test_forecast_path_retention_preserves_run_metadata() -> None:
    retention_impl = _function_source("prune_forecast_paths").lower()

    assert "delete from forecast_paths" in retention_impl
    assert "delete from forecast_runs" not in retention_impl
    assert "vacuum forecast_paths" in retention_impl


def test_forecast_path_retention_protects_in_flight_valuations() -> None:
    retention_impl = _function_source("prune_forecast_paths").lower()

    assert "from valuations" in retention_impl
    assert "forecast_run_id is not null" in retention_impl
    # Re-check queued/running valuations both when selecting candidates and
    # again in the DELETE, closing the selection-to-deletion race.
    assert retention_impl.count("status in ('queued', 'running')") == 2
