from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]


def test_daily_regime_infer_window_satisfies_model_minimum() -> None:
    modal_source = (WORKER_ROOT / "modal_app.py").read_text()
    infer_source = (WORKER_ROOT / "regime" / "infer_state.py").read_text()

    assert "_MIN_INFER_RESIDUALS = 200" in infer_source
    assert "len(resids.residuals) < _MIN_INFER_RESIDUALS" in infer_source
    assert "today - timedelta(days=14)" in modal_source
    assert "today - timedelta(days=2)" not in modal_source
