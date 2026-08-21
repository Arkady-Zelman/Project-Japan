"""Regression guards for high-impact worker correctness issues.

These tests intentionally read source text instead of importing modal_app:
Modal and cloud dependencies are not required to catch destructive SQL
regressions in retention wiring.
"""

from __future__ import annotations

import ast
from pathlib import Path

WORKER_ROOT = Path(__file__).resolve().parents[1]
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

    assert "delete from forecast_paths fp" in source
    # Check active references both when selecting candidates and again in the
    # DELETE statement, closing the selection-to-deletion race.
    assert source.count("from valuations") == 2
    assert source.count("status in ('queued', 'running')") == 2


def test_daily_stack_build_restores_model_lookback() -> None:
    source = MODAL_APP.read_text()
    stack_source = _function_source("stack_run_daily")

    assert "_STACK_DAILY_LOOKBACK_DAYS = 8" in source
    assert "timedelta(days=_stack_daily_lookback_days)" in stack_source
    assert "timedelta(days=1)" not in stack_source


def test_lsm_fails_closed_on_incomplete_or_stale_valuations() -> None:
    runner = (WORKER_ROOT / "lsm" / "runner.py").read_text()

    assert "incomplete forecast paths:" in runner
    assert "expected queued" in runner
    assert "and status in ('queued', 'running')" in runner
    assert 'logger.warning(\n            "forecast_paths row count' not in runner


def test_backtest_fails_closed_on_stale_rows() -> None:
    runner = (WORKER_ROOT / "backtest" / "runner.py").read_text()

    assert "expected queued" in runner
    assert "and status in ('queued', 'running')" in runner
    assert (
        "update backtests set status='failed', error=%s, completed_at=now() where id = %s"
        not in runner
    )


def test_auth_callback_sanitizes_next_redirect() -> None:
    repo_root = WORKER_ROOT.parents[1]
    callback = (
        repo_root / "apps/web/src/app/auth/callback/route.ts"
    ).read_text(encoding="utf-8")
    redirect_helper = (
        repo_root / "apps/web/src/lib/auth/redirect.ts"
    ).read_text(encoding="utf-8")

    assert "sanitizeNextPath" in callback
    assert "export function sanitizeNextPath" in redirect_helper
    assert 'next.startsWith("/")' in redirect_helper
    assert 'next.startsWith("//")' in redirect_helper
