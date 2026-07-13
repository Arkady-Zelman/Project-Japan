"""Static regression guards for Modal retention jobs.

These tests deliberately avoid importing ``modal_app`` because Modal and the
worker dependency stack are not always installed in lightweight CI images. The
failure mode they guard is textual SQL returning to a scheduled job.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODAL_APP = ROOT / "modal_app.py"

CANONICAL_TABLES = {
    "jepx_spot_prices",
    "demand_actuals",
    "generation_mix_actuals",
    "weather_obs",
    "stack_curves",
    "stack_clearing_prices",
    "regime_states",
}


def _modal_source() -> str:
    return MODAL_APP.read_text(encoding="utf-8")


def _compact_sqlish(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _function_block(source: str, name: str) -> str:
    match = re.search(rf"^def {name}\(.*?^def ", source, flags=re.MULTILINE | re.DOTALL)
    if match:
        return match.group(0)[:-5]
    match = re.search(rf"^def {name}\(.*", source, flags=re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError(f"{name} not found in modal_app.py")
    return match.group(0)


def test_retention_never_deletes_canonical_historical_tables() -> None:
    """Nightly retention must not erase training/backtest/dashboard inputs."""
    source = _compact_sqlish(_modal_source())

    assert "truncate table" not in source
    for table in CANONICAL_TABLES:
        assert f"delete from {table}" not in source


def test_forecast_retention_preserves_forecast_run_parents() -> None:
    """`valuations.forecast_run_id` references parent rows without cascade."""
    block = _compact_sqlish(_function_block(_modal_source(), "prune_forecast_paths"))

    assert "delete from forecast_paths" in block
    assert "delete from forecast_runs" not in block
    assert "v.status in ('queued', 'running')" in block


def test_legacy_and_nightly_prune_entrypoints_are_forecast_only() -> None:
    source = _modal_source()
    old_data_block = _compact_sqlish(_function_block(source, "prune_old_data"))
    nightly_block = _compact_sqlish(_function_block(source, "prune_nightly"))

    assert "prune_forecast_paths.local()" in old_data_block
    assert "prune_forecast_paths.local()" in nightly_block
    for table in CANONICAL_TABLES:
        assert table not in old_data_block
        assert table not in nightly_block
