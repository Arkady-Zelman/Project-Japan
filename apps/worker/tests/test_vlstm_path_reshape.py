"""Unit tests for forecast_paths reshape used by lsm_vlstm."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from backtest.vlstm_paths import reshape_forecast_path_rows


def test_reshape_orders_columns_by_slot_and_drops_incomplete_paths() -> None:
    t0 = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 1, 0, 30, tzinfo=UTC)
    rows = [
        (0, t0, 10.0),
        (1, t0, 11.0),
        (0, t1, 12.0),
        # path 1 missing t1 — must be dropped, not zero-padded
    ]

    mat = reshape_forecast_path_rows(rows)

    assert mat is not None
    assert mat.shape == (1, 2)
    np.testing.assert_allclose(mat[0], [10.0, 12.0])


def test_reshape_empty_or_all_incomplete_is_none() -> None:
    assert reshape_forecast_path_rows([]) is None

    t0 = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 1, 0, 30, tzinfo=UTC)
    # Two paths, each missing a different slot.
    rows = [
        (0, t0, 10.0),
        (1, t1, 11.0),
    ]
    assert reshape_forecast_path_rows(rows) is None
