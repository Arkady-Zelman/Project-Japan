"""Regression guards for high-impact worker correctness issues.

These tests inspect source instead of importing ``modal_app`` so cloud
dependencies are not required to detect destructive retention wiring.
"""

from __future__ import annotations

import ast
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKER_ROOT.parents[1]
MODAL_APP = WORKER_ROOT / "modal_app.py"


def _function_source(name: str) -> str:
    source = MODAL_APP.read_text()
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment.lower()
    raise AssertionError(f"{name} not found in {MODAL_APP}")


def test_retention_never_deletes_canonical_history_tables() -> None:
    retention_source = "\n".join(
        [
            _function_source("prune_forecast_paths"),
            _function_source("prune_old_data"),
            _function_source("prune_nightly"),
        ]
    )

    forbidden_fragments = [
        "truncate table",
        "delete from jepx_spot_prices",
        "delete from demand_actuals",
        "delete from generation_mix_actuals",
        "delete from weather_obs",
        "delete from regime_states",
        "delete from stack_curves",
        "delete from stack_clearing_prices",
        "delete from forecast_runs",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in retention_source


def test_forecast_retention_preserves_active_valuation_inputs() -> None:
    source = _function_source("prune_forecast_paths")

    assert "delete from forecast_paths" in source
    assert "from valuations" in source
    assert "status in ('queued', 'running')" in source


def test_daily_stack_build_self_heals_forecast_lookback() -> None:
    source = MODAL_APP.read_text()

    assert "_STACK_DAILY_LOOKBACK_DAYS = 8" in source
    assert "start = today - timedelta(days=_STACK_DAILY_LOOKBACK_DAYS)" in source
    assert "out = build_window(start, today)" in source


def test_bos_demo_asset_uses_fractional_soc_limits() -> None:
    source = (
        REPO_ROOT / "apps/web/src/app/api/bos-strategy/route.ts"
    ).read_text()

    assert "soc_min_pct: 0.10" in source
    assert "soc_max_pct: 0.90" in source
    assert "soc_min_pct: 10" not in source
    assert "soc_max_pct: 90" not in source


def test_forecast_path_pagination_has_stable_ordering() -> None:
    bos_source = (
        REPO_ROOT / "apps/web/src/app/api/bos-strategy/route.ts"
    ).read_text()
    fan_source = (
        REPO_ROOT / "apps/web/src/app/api/forecast-paths/route.ts"
    ).read_text()

    for source in (bos_source, fan_source):
        assert '.order("slot_start", { ascending: true })' in source
        assert '.order("path_id", { ascending: true })' in source
