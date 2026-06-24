from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "modal_app.py"


def _function_body(source: str, name: str) -> str:
    marker = f"def {name}("
    start = source.index(marker)
    next_def = source.find("\n@app.function", start + len(marker))
    if next_def == -1:
        next_def = len(source)
    return source[start:next_def]


def test_nightly_retention_does_not_delete_canonical_history_tables() -> None:
    source = SOURCE.read_text()
    prune_body = _function_body(source, "prune_old_data").lower()
    nightly_body = _function_body(source, "prune_nightly").lower()

    forbidden_snippets = [
        "truncate table stack_curves",
        "truncate table stack_clearing_prices",
        "delete from stack_curves",
        "delete from stack_clearing_prices",
        "delete from regime_states",
        "delete from generation_mix_actuals",
        "delete from demand_actuals",
        "delete from jepx_spot_prices",
        "delete from weather_obs",
    ]
    for body in (prune_body, nightly_body):
        for snippet in forbidden_snippets:
            assert snippet not in body


def test_forecast_path_retention_preserves_run_metadata_and_inflight_inputs() -> None:
    source = SOURCE.read_text()
    helper_body = _function_body(source, "_prune_forecast_paths_impl").lower()

    assert "delete from forecast_paths" in helper_body
    assert "delete from forecast_runs" not in helper_body
    assert "status in ('queued', 'running')" in helper_body


def test_legacy_prune_entrypoints_route_to_safe_forecast_path_helper() -> None:
    source = SOURCE.read_text()
    prune_body = _function_body(source, "prune_old_data")
    nightly_body = _function_body(source, "prune_nightly")

    assert "_prune_forecast_paths_impl(retain_latest_per_area=2)" in prune_body
    assert "_prune_forecast_paths_impl(retain_latest_per_area=2)" in nightly_body
