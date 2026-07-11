from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[3]


def read_repo(path: str) -> str:
    return (WORKSPACE / path).read_text(encoding="utf-8")


def test_nightly_retention_preserves_canonical_history() -> None:
    modal_app = read_repo("apps/worker/modal_app.py").lower()

    assert "truncate table stack_curves" not in modal_app
    assert '"jepx_spot_prices", 90' not in modal_app
    assert '"demand_actuals", 90' not in modal_app
    assert '"generation_mix_actuals", 90' not in modal_app
    assert "delete from forecast_runs" not in modal_app
    assert "delete from forecast_paths where forecast_run_id" in modal_app
    assert "v.status in ('queued', 'running')" in modal_app


def test_public_modal_endpoints_require_shared_bearer_token() -> None:
    modal_app = read_repo("apps/worker/modal_app.py")

    assert "def _require_modal_api_token(authorization: str | None) -> None:" in modal_app
    assert "hmac.compare_digest(token, expected)" in modal_app
    assert "def lsm_value(payload: dict, authorization: str | None = Header(default=None))" in modal_app
    assert "def run_backtest(payload: dict, authorization: str | None = Header(default=None))" in modal_app
    assert modal_app.count("_require_modal_api_token(authorization)") >= 2


def test_nextjs_modal_proxies_forward_shared_token() -> None:
    value_route = read_repo("apps/web/src/app/api/value-asset/route.ts")
    backtest_route = read_repo("apps/web/src/app/api/run-backtest/route.ts")

    for route in (value_route, backtest_route):
        assert "const MODAL_API_TOKEN = process.env.MODAL_API_TOKEN;" in route
        assert "MODAL_API_TOKEN not configured" in route
        assert "authorization: `Bearer ${MODAL_API_TOKEN}`" in route


def test_compute_workers_reject_non_queued_replays_without_overwriting_done_rows() -> None:
    lsm_runner = read_repo("apps/worker/lsm/runner.py")
    backtest_runner = read_repo("apps/worker/backtest/runner.py")

    assert "v[\"status\"] != \"queued\"" in lsm_runner
    assert "expected queued" in lsm_runner
    assert "status in ('queued', 'running')" in lsm_runner

    assert "row[\"status\"] != \"queued\"" in backtest_runner
    assert "expected queued" in backtest_runner
    assert "status in ('queued', 'running')" in backtest_runner


def test_bos_strategy_uses_stable_forecast_pages_and_truthful_source() -> None:
    route = read_repo("apps/web/src/app/api/bos-strategy/route.ts")
    client = read_repo("apps/web/src/components/dashboard/StrategyTab.tsx")

    assert 'soc_min_pct: 0.10' in route
    assert 'soc_max_pct: 0.90' in route
    assert 'let actualSource: "forecast" | "realised" = source;' in route
    assert 'source: actualSource' in route
    assert '.order("slot_start", { ascending: true })' in route
    assert '.order("path_id", { ascending: true })' in route
    assert "setSource(j.source as Forecast)" in client
