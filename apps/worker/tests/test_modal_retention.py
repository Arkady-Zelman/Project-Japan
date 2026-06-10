from __future__ import annotations

from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
MODAL_APP = WORKER_ROOT / "modal_app.py"


def _function_body(source: str, name: str) -> str:
    start = source.index(f"def {name}(")
    next_def = source.find("\n@app.function", start + 1)
    if next_def == -1:
        return source[start:]
    return source[start:next_def]


def test_nightly_retention_only_prunes_forecast_paths() -> None:
    source = MODAL_APP.read_text()
    body = _function_body(source, "prune_nightly")

    assert "prune_forecast_paths.local(retain_latest_per_area=2)" in body
    assert "prune_old_data.local()" not in body


def test_old_data_prune_does_not_delete_canonical_history() -> None:
    source = MODAL_APP.read_text()
    body = _function_body(source, "prune_old_data")
    lowered = body.lower()

    assert "prune_forecast_paths.local(retain_latest_per_area=2)" in body
    assert "truncate table" not in lowered

    canonical_tables = [
        "jepx_spot_prices",
        "demand_actuals",
        "generation_mix_actuals",
        "weather_obs",
        "stack_curves",
        "stack_clearing_prices",
        "regime_states",
    ]
    for table in canonical_tables:
        assert f"delete from {table}" not in lowered
