from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / "apps" / "worker"
WEB = ROOT / "apps" / "web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(source: str, name: str) -> str:
    match = re.search(rf"^def {name}\(.*?(?=^def |^@app\.function|\Z)", source, re.M | re.S)
    assert match, f"{name} not found"
    return match.group(0)


def test_nightly_retention_preserves_canonical_history_tables() -> None:
    modal_app = _read(WORKER / "modal_app.py")
    prune_old_data = _function_source(modal_app, "prune_old_data")
    prune_nightly = _function_source(modal_app, "prune_nightly")

    destructive_phrases = [
        "truncate table stack_curves",
        "delete from jepx_spot_prices",
        "delete from demand_actuals",
        "delete from generation_mix_actuals",
        "delete from weather_obs",
        "delete from regime_states",
        "delete from stack_curves",
        "delete from stack_clearing_prices",
    ]
    combined = f"{prune_old_data}\n{prune_nightly}".lower()
    for phrase in destructive_phrases:
        assert phrase not in combined

    assert "prune_forecast_paths.local" in prune_nightly


def test_forecast_retention_keeps_parent_runs_and_inflight_paths() -> None:
    modal_app = _read(WORKER / "modal_app.py")
    impl = _function_source(modal_app, "_prune_forecast_paths_impl")

    assert "delete from forecast_paths" in impl.lower()
    assert "delete from forecast_runs" not in impl.lower()
    assert "v.status in ('queued', 'running')" in impl


def test_auth_callback_sanitizes_next_redirect() -> None:
    callback = _read(WEB / "src" / "app" / "auth" / "callback" / "route.ts")
    sanitizer = _read(WEB / "src" / "lib" / "auth" / "redirect.ts")

    assert "sanitizeNextPath" in callback
    assert 'next.startsWith("//")' in sanitizer
    assert "CONTROL_OR_BACKSLASH" in sanitizer
    assert "parsed.origin !== SAME_ORIGIN_BASE" in sanitizer


def test_bos_demo_uses_fractional_soc_and_stable_forecast_pagination() -> None:
    route = _read(WEB / "src" / "app" / "api" / "bos-strategy" / "route.ts")

    assert "soc_min_pct: 0.10" in route
    assert "soc_max_pct: 0.90" in route
    assert '.order("slot_start", { ascending: true })' in route
    assert '.order("path_id", { ascending: true })' in route


def test_public_dashboard_does_not_expose_raw_compute_errors() -> None:
    page = _read(WEB / "src" / "app" / "(app)" / "dashboard" / "page.tsx")

    assert "PUBLIC_ERROR_MESSAGE" in page
    assert "sanitizeRunError" in page
    assert '.is("user_id", null)' in page


def test_lsm_vlstm_backtest_matches_forecast_path_schema() -> None:
    loader = _read(WORKER / "backtest" / "vlstm_paths.py")
    migration = _read(ROOT / "supabase" / "migrations" / "008_lsm_vlstm_backtest_strategy.sql")

    assert "select path_id, slot_start, price_jpy_kwh" in loader
    assert "where forecast_run_id = %s" in loader
    assert "path_index" not in loader
    assert "slot_ix < %s" not in loader
    assert "run_id = %s" not in loader
    assert "lsm_vlstm" in migration
