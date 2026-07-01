from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_nightly_retention_only_prunes_generated_forecast_paths() -> None:
    modal_app = _read("apps/worker/modal_app.py")

    assert "_prune_forecast_paths_impl" in modal_app
    assert "delete from forecast_paths" in modal_app
    assert "delete from forecast_runs" not in modal_app
    assert "truncate table stack_curves" not in modal_app.lower()

    for table in (
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "stack_curves",
        "stack_clearing_prices",
        "regime_states",
    ):
        assert f"delete from {table}" not in modal_app.lower()

    assert "v.status in ('queued', 'running')" in modal_app
    assert "return _prune_forecast_paths_impl(retain_latest_per_area=2)" in modal_app


def test_daily_regime_infer_window_satisfies_mrs_minimum() -> None:
    modal_app = _read("apps/worker/modal_app.py")
    infer_state = _read("apps/worker/regime/infer_state.py")

    assert "today - timedelta(days=14)" in modal_app
    assert "_MIN_INFER_RESIDUALS = 200" in infer_state
    assert "len(resids.residuals) < _MIN_INFER_RESIDUALS" in infer_state
    assert "len(resids.residuals) < 50" not in infer_state


def test_user_compute_runs_are_not_public_system_health_rows() -> None:
    migration = _read("supabase/migrations/008_compute_runs_rls.sql")
    dashboard_page = _read("apps/web/src/app/(app)/dashboard/page.tsx")
    dashboard_client = _read("apps/web/src/components/dashboard/DashboardClient.tsx")
    lsm_runner = _read("apps/worker/lsm/runner.py")
    backtest_runner = _read("apps/worker/backtest/runner.py")
    agent_tools = _read("apps/worker/agent/tools.py")

    assert "user_id = auth.uid() or user_id is null" not in migration
    assert "users_read_own_compute_runs" in migration
    assert "public_read_system_compute_runs" in migration
    assert "'lsm_valuation'" not in migration
    assert "'backtest'" not in migration
    assert "'agent_tool_call'" not in migration

    assert 'compute_run("lsm_valuation", user_id=audit_user_id)' in lsm_runner
    assert 'compute_run("backtest", user_id=audit_user_id)' in backtest_runner
    assert 'compute_run("agent_tool_call", user_id=ctx.user_id)' in agent_tools

    assert '.is("user_id", null)' in dashboard_page
    assert '"lsm_valuation"' not in dashboard_page
    assert '"backtest"' not in dashboard_page
    assert '"lsm_valuation"' not in dashboard_client
    assert '"backtest"' not in dashboard_client


def test_completed_jobs_are_not_overwritten_or_marked_failed_by_retries() -> None:
    lsm_runner = _read("apps/worker/lsm/runner.py")
    backtest_runner = _read("apps/worker/backtest/runner.py")

    assert "expected queued" in lsm_runner
    assert "expected queued" in backtest_runner
    assert "and status in ('queued', 'running')" in lsm_runner
    assert "and status in ('queued', 'running')" in backtest_runner
