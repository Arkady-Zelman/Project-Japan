"""Regression checks for Modal retention jobs.

These tests intentionally inspect the source instead of importing modal_app:
importing the Modal app requires the Modal package and image setup, while the
bug this guards was a scheduled retention contract violation visible in source.
"""

from __future__ import annotations

import re
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"

CANONICAL_TABLES = {
    "jepx_spot_prices",
    "demand_actuals",
    "generation_mix_actuals",
    "weather_obs",
    "stack_curves",
    "stack_clearing_prices",
    "regime_states",
}


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"^def {name}\([^)]*\).*?(?=^def |\Z)", source, re.M | re.S)
    assert match is not None, f"{name} not found"
    return match.group(0)


def test_nightly_prune_only_prunes_forecast_paths() -> None:
    source = MODAL_APP.read_text(encoding="utf-8")

    body = _function_body(source, "prune_old_data")

    assert "prune_forecast_paths.local(retain_latest_per_area=2)" in body
    assert "truncate" not in body.lower()
    assert "delete from" not in body.lower()
    for table in CANONICAL_TABLES:
        assert table not in body


def test_stack_daily_spawns_safe_retention_wrapper() -> None:
    source = MODAL_APP.read_text(encoding="utf-8")

    body = _function_body(source, "stack_run_daily")

    assert "prune_nightly.spawn()" in body
    assert "truncate" not in body.lower()
