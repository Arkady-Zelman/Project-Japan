"""Static safety guards for Modal retention jobs.

These tests intentionally avoid importing modal_app.py because Modal and the
runtime secrets are not required to validate the retention contract.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODAL_APP = ROOT / "modal_app.py"

CANONICAL_HISTORY_TABLES = (
    "jepx_spot_prices",
    "demand_actuals",
    "generation_mix_actuals",
    "weather_obs",
    "regime_states",
    "stack_curves",
    "stack_clearing_prices",
)


def _source() -> str:
    return MODAL_APP.read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    source = _source()
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"function {name} not found")


def test_retention_never_deletes_canonical_history_tables() -> None:
    """Nightly retention must not erase historical inputs used downstream."""

    retention_source = "\n".join(
        _function_source(name)
        for name in ("_prune_forecast_paths_impl", "prune_forecast_paths", "prune_old_data", "prune_nightly")
    ).lower()

    forbidden_fragments = []
    for table in CANONICAL_HISTORY_TABLES:
        forbidden_fragments.extend(
            (
                f"delete from {table}",
                f"truncate table {table}",
                f"truncate {table}",
            )
        )

    found = [fragment for fragment in forbidden_fragments if fragment in retention_source]
    assert found == []


def test_forecast_path_retention_preserves_parent_runs_and_active_valuations() -> None:
    """Only forecast_paths rows are pruned; forecast_runs and active LSM inputs stay."""

    retention_source = _function_source("_prune_forecast_paths_impl").lower()

    assert "delete from forecast_paths" in retention_source
    assert "delete from forecast_runs" not in retention_source
    assert "truncate" not in retention_source
    assert "not exists" in retention_source
    assert "from valuations" in retention_source
    assert "status in ('queued', 'running')" in retention_source


def test_legacy_and_scheduled_entrypoints_use_safe_retention_helper() -> None:
    """The old on-demand name and nightly cron must share the safe helper."""

    assert "_prune_forecast_paths_impl(retain_latest_per_area=2)" in _function_source("prune_old_data")
    assert "_prune_forecast_paths_impl(retain_latest_per_area=2)" in _function_source("prune_nightly")
