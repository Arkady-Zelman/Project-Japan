"""Regression tests for critical correctness/security contracts."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_nightly_retention_only_prunes_generated_forecast_paths() -> None:
    source = _read("apps/worker/modal_app.py")
    prune_old_data = re.search(
        r"def prune_old_data\(\) -> dict:(?P<body>.*?)\n\n@app\.function",
        source,
        flags=re.S,
    )
    assert prune_old_data is not None
    body = prune_old_data.group("body").lower()

    assert "prune_forecast_paths.local" in body
    assert "truncate table" not in body
    assert "delete from" not in body

    nightly = re.search(
        r"def prune_nightly\(\) -> dict:(?P<body>.*?return prune_old_data\.local\(\))",
        source,
        flags=re.S,
    )
    assert nightly is not None


def test_user_triggered_compute_runs_are_tenant_tagged() -> None:
    lsm_runner = _read("apps/worker/lsm/runner.py")
    assert 'compute_run("lsm_valuation", user_id=user_id)' in lsm_runner
    assert "def _load_valuation_user_id" in lsm_runner

    backtest_runner = _read("apps/worker/backtest/runner.py")
    assert 'compute_run("backtest", user_id=user_id)' in backtest_runner
    assert "def _load_backtest_user_id" in backtest_runner

    agent_tools = _read("apps/worker/agent/tools.py")
    assert 'compute_run("agent_tool_call") as run' not in agent_tools
    assert agent_tools.count('compute_run("agent_tool_call", user_id=ctx.user_id)') == 7


def test_compute_runs_policy_does_not_publish_sensitive_null_user_kinds() -> None:
    migration = _read("supabase/migrations/008_compute_runs_tenancy.sql")
    public_kind_list = re.search(r"kind in \((?P<kinds>.*?)\)", migration, flags=re.S)
    assert public_kind_list is not None
    kinds = public_kind_list.group("kinds")

    assert "'lsm_valuation'" not in kinds
    assert "'backtest'" not in kinds
    assert "'agent_tool_call'" not in kinds
    assert "cr.input->>'valuation_id' = v.id::text" in migration
    assert "cr.input->>'backtest_id' = b.id::text" in migration


def test_public_bos_demo_asset_uses_fractional_soc_units() -> None:
    route = _read("apps/web/src/app/api/bos-strategy/route.ts")
    demo_block = re.search(
        r'assetMeta = \{ id: "demo".*?assetSpec = \{(?P<body>.*?)\n    \};',
        route,
        flags=re.S,
    )
    assert demo_block is not None
    body = demo_block.group("body")

    assert "soc_min_pct: 0.10" in body
    assert "soc_max_pct: 0.90" in body
    assert "soc_min_pct: 10" not in body
    assert "soc_max_pct: 90" not in body
