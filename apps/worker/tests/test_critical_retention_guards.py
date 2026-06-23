"""Static guards for high-impact retention and demo-unit regressions.

These tests intentionally avoid importing modal_app.py, because importing the
Modal module pulls in deployment-time dependencies that are not always present
in lightweight CI or cloud-agent validation images.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def _function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"function {name} not found")


def test_modal_retention_only_prunes_generated_forecast_paths() -> None:
    source = _read("apps/worker/modal_app.py")
    lowered = source.lower()
    helper = _function_source(source, "_prune_forecast_paths_impl").lower()
    prune_old = _function_source(source, "prune_old_data").lower()
    prune_nightly = _function_source(source, "prune_nightly").lower()

    assert "truncate table stack_curves" not in lowered
    assert "truncate table stack_clearing_prices" not in lowered
    assert "delete from forecast_runs" not in lowered

    for canonical_table in (
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "regime_states",
        "stack_curves",
        "stack_clearing_prices",
    ):
        assert canonical_table not in prune_old

    assert "delete from forecast_paths" in helper
    assert "from valuations" in helper
    assert "queued" in helper
    assert "running" in helper
    assert "_prune_forecast_paths_impl" in prune_nightly
    assert "prune_old_data" not in prune_nightly


def test_public_bos_demo_uses_fractional_soc_bounds() -> None:
    route = _read("apps/web/src/app/api/bos-strategy/route.ts")
    demo_start = route.index('assetMeta = { id: "demo"')
    demo_block = route[demo_start:]

    assert "soc_min_pct: 0.10" in demo_block
    assert "soc_max_pct: 0.90" in demo_block
    assert re.search(r"soc_min_pct:\s*10\b", demo_block) is None
    assert re.search(r"soc_max_pct:\s*90\b", demo_block) is None
