from __future__ import annotations

from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (WORKER_ROOT / relative_path).read_text(encoding="utf-8").lower()


def test_nightly_retention_does_not_delete_canonical_history() -> None:
    source = _source("modal_app.py")

    forbidden_snippets = [
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
    for snippet in forbidden_snippets:
        assert snippet not in source


def test_forecast_retention_preserves_runs_and_active_valuation_paths() -> None:
    source = _source("modal_app.py")

    assert "delete from forecast_paths where forecast_run_id" in source
    assert "delete from forecast_runs" not in source
    assert "v.status in ('queued', 'running')" in source
    assert "def prune_nightly" in source
    assert "return prune_old_data.local()" in source
    assert "_prune_forecast_paths_impl(retain_latest_per_area=2)" in source


def test_vlstm_backtest_loader_uses_forecast_paths_schema() -> None:
    source = _source("backtest/vlstm_paths.py")

    for obsolete_name in ["path_index", "slot_ix", "where run_id"]:
        assert obsolete_name not in source
    assert "select path_id, slot_start, price_jpy_kwh" in source
    assert "where forecast_run_id = %s" in source
    assert "and slot_start >= %s" in source
    assert "order by slot_start, path_id" in source
