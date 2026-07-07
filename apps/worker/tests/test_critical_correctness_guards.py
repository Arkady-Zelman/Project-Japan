"""Static guards for high-blast-radius safety contracts.

These tests intentionally avoid importing Modal, psycopg, or the app packages;
they can run in a clean CI worker and still catch the exact regressions that
would otherwise delete canonical history or expose user audit rows.
"""

from __future__ import annotations

from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKER_ROOT.parents[1]


def _read_repo(path: str) -> str:
    return (REPO_ROOT / path).read_text()


def test_nightly_retention_only_prunes_forecast_path_children() -> None:
    modal_app = _read_repo("apps/worker/modal_app.py").lower()

    forbidden_sql = [
        "truncate table stack_curves",
        "delete from stack_curves",
        "delete from stack_clearing_prices",
        "delete from regime_states",
        "delete from generation_mix_actuals",
        "delete from demand_actuals",
        "delete from jepx_spot_prices",
        "delete from weather_obs",
        "delete from forecast_runs",
    ]
    for sql in forbidden_sql:
        assert sql not in modal_app

    assert "return prune_old_data.local()" in modal_app
    assert "out = prune_forecast_paths.local()" in modal_app
    assert "delete from forecast_paths where forecast_run_id" in modal_app
    assert "status in ('queued', 'running')" in modal_app
    assert 'compute_run("forecast_path_retention")' in modal_app


def test_user_compute_audit_rows_are_owner_scoped() -> None:
    lsm_runner = _read_repo("apps/worker/lsm/runner.py")
    backtest_runner = _read_repo("apps/worker/backtest/runner.py")
    agent_tools = _read_repo("apps/worker/agent/tools.py")

    assert 'compute_run("lsm_valuation", user_id=owner_id)' in lsm_runner
    assert "def _load_valuation_owner" in lsm_runner
    assert "expected queued" in lsm_runner
    assert "and status in ('queued', 'running')" in lsm_runner

    assert 'compute_run("backtest", user_id=owner_id)' in backtest_runner
    assert "def _load_backtest_owner" in backtest_runner
    assert "expected queued" in backtest_runner
    assert "and status in ('queued', 'running')" in backtest_runner

    assert agent_tools.count('compute_run("agent_tool_call", user_id=ctx.user_id)') == 7
    assert 'with compute_run("agent_tool_call") as run' not in agent_tools


def test_public_compute_runs_policy_and_dashboard_exclude_user_jobs() -> None:
    migration = _read_repo("supabase/migrations/008_compute_runs_rls.sql")
    dashboard_page = _read_repo("apps/web/src/app/(app)/dashboard/page.tsx")
    dashboard_client = _read_repo("apps/web/src/components/dashboard/DashboardClient.tsx")

    assert 'drop policy if exists "users_own_compute_runs"' in migration
    assert "user_id = auth.uid()" in migration
    assert "user_id is null" in migration
    public_policy = migration.split('create policy "public_system_compute_runs"', 1)[1]
    for private_kind in ("lsm_valuation", "backtest", "agent_tool_call"):
        assert f"'{private_kind}'" not in public_policy

    assert '.is("user_id", null)' in dashboard_page
    for private_kind in ("lsm_valuation", "backtest", "agent_tool_call"):
        assert f'"{private_kind}"' not in dashboard_page
        assert f'"{private_kind}"' not in dashboard_client
