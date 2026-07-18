"""Static guards for destructive scheduled-job regressions.

These tests intentionally avoid importing ``modal_app`` so they run without
building Modal images or requiring production secrets.
"""

from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
MODAL_APP = (WORKER_ROOT / "modal_app.py").read_text()
INFER_STATE = (WORKER_ROOT / "regime" / "infer_state.py").read_text()


def _function_body(source: str, name: str, next_marker: str) -> str:
    start = source.index(f"def {name}(")
    end = source.index(next_marker, start)
    return source[start:end]


def test_retention_only_deletes_forecast_path_children() -> None:
    retention = _function_body(
        MODAL_APP,
        "prune_forecast_paths",
        "@app.function(image=base_image, cpu=2.0, timeout=3600",
    )

    assert "delete from forecast_paths" in retention
    assert "delete from forecast_runs" not in retention
    assert "v.status in ('queued', 'running')" in retention
    assert "truncate table" not in MODAL_APP.lower()


def test_retention_aliases_use_safe_path_pruning() -> None:
    old_data = _function_body(
        MODAL_APP,
        "prune_old_data",
        "@app.function(image=base_image, secrets=_secrets)",
    )
    nightly = _function_body(
        MODAL_APP,
        "prune_nightly",
        "@app.function(image=base_image, cpu=4.0, timeout=1800",
    )

    assert "return prune_forecast_paths.local()" in old_data
    assert "return prune_forecast_paths.local()" in nightly


def test_daily_regime_inference_clears_model_observation_floor() -> None:
    daily = _function_body(
        MODAL_APP,
        "regime_infer_daily",
        "@app.function(image=base_image, cpu=2.0, timeout=3600",
    )

    assert "today - timedelta(days=14)" in daily
    assert "_MIN_INFER_RESIDUALS = 200" in INFER_STATE
    assert "len(resids.residuals) < _MIN_INFER_RESIDUALS" in INFER_STATE
