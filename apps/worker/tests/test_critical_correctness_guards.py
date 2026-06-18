from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _function_source(path: Path, name: str) -> str:
    text = path.read_text()
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            lines = text.splitlines()
            return "\n".join(lines[node.lineno - 1: node.end_lineno])
    raise AssertionError(f"function {name} not found in {path}")


def test_nightly_retention_only_prunes_forecast_path_payloads() -> None:
    modal_app = ROOT / "apps/worker/modal_app.py"
    impl = _function_source(modal_app, "_prune_forecast_paths_impl")
    nightly = _function_source(modal_app, "prune_nightly")
    compatibility_entry = _function_source(modal_app, "prune_old_data")

    assert "_prune_forecast_paths_impl" in nightly
    assert "_prune_forecast_paths_impl" in compatibility_entry
    assert "prune_old_data.local" not in nightly

    assert "delete from forecast_paths" in impl
    assert "delete from forecast_runs" not in impl
    assert "status in ('queued','running')" in impl

    forbidden_canonical_tables = [
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "regime_states",
        "stack_curves",
        "stack_clearing_prices",
    ]
    for table in forbidden_canonical_tables:
        assert table not in impl
    assert "truncate" not in impl.lower()


def test_auth_redirects_are_sanitized_before_post_login_redirect() -> None:
    helper = (ROOT / "apps/web/src/lib/auth/redirect.ts").read_text()
    login_page = (ROOT / "apps/web/src/app/login/page.tsx").read_text()
    callback = (ROOT / "apps/web/src/app/auth/callback/route.ts").read_text()

    assert "sanitizeNextPath(searchParams.next)" in login_page
    assert "sanitizeNextPath(url.searchParams.get(\"next\"))" in callback
    assert "candidate.startsWith(\"//\")" in helper
    assert "candidate.includes(\"\\\\\")" in helper


def test_bos_demo_asset_uses_fractional_soc_bounds() -> None:
    route = (ROOT / "apps/web/src/app/api/bos-strategy/route.ts").read_text()

    assert "soc_min_pct: 0.10" in route
    assert "soc_max_pct: 0.90" in route
    assert "asset SoC limits must be fractions between 0 and 1" in route
