from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"


def test_retention_does_not_delete_canonical_history() -> None:
    source = MODAL_APP.read_text()
    lowered = source.lower()

    forbidden_fragments = [
        "truncate table stack_curves",
        "truncate stack_curves",
        "delete from stack_curves",
        "delete from stack_clearing_prices",
        "delete from jepx_spot_prices",
        "delete from demand_actuals",
        "delete from generation_mix_actuals",
        "delete from weather_obs",
        "delete from regime_states",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in lowered


def test_forecast_retention_preserves_parent_runs() -> None:
    source = MODAL_APP.read_text().lower()

    assert "delete from forecast_paths" in source
    assert "delete from forecast_runs" not in source
    assert "v.status in ('queued', 'running')" in source
