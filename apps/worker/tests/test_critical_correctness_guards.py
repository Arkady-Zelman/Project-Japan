from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_modal_retention_does_not_delete_canonical_history() -> None:
    source = read("apps/worker/modal_app.py")
    lowered = source.lower()

    assert "truncate table stack_curves" not in lowered
    assert "delete from stack_curves" not in lowered
    assert "delete from stack_clearing_prices" not in lowered
    assert "delete from jepx_spot_prices" not in lowered
    assert "delete from demand_actuals" not in lowered
    assert "delete from generation_mix_actuals" not in lowered
    assert "delete from weather_obs" not in lowered
    assert "delete from regime_states" not in lowered


def test_modal_retention_prunes_only_forecast_path_rows() -> None:
    source = read("apps/worker/modal_app.py").lower()

    assert "return prune_forecast_paths.local(retain_latest_per_area=2)" in source
    assert "delete from forecast_paths where forecast_run_id = %s" in source
    assert "delete from forecast_runs" not in source


def test_daily_stack_build_self_heals_minimum_lookback() -> None:
    source = read("apps/worker/modal_app.py")

    assert "_STACK_DAILY_LOOKBACK_DAYS = 8" in source
    assert "start = today - timedelta(days=_STACK_DAILY_LOOKBACK_DAYS)" in source
    assert "out = build_window(start, today)" in source


def test_bos_demo_asset_uses_fractional_soc_limits() -> None:
    source = read("apps/web/src/app/api/bos-strategy/route.ts")

    assert "soc_min_pct: 0.10" in source
    assert "soc_max_pct: 0.90" in source
    assert "soc_min_pct: 10" not in source
    assert "soc_max_pct: 90" not in source


def test_forecast_path_pagination_has_stable_ordering() -> None:
    bos_source = read("apps/web/src/app/api/bos-strategy/route.ts")
    fan_source = read("apps/web/src/app/api/forecast-paths/route.ts")

    assert '.order("slot_start", { ascending: true })' in bos_source
    assert '.order("path_id", { ascending: true })' in bos_source
    assert '.order("slot_start", { ascending: true })' in fan_source
    assert '.order("path_id", { ascending: true })' in fan_source
