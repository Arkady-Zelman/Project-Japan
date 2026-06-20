from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from lsm.runner import _load_forecast_paths


class FakeCursor:
    def __init__(self, rows: list[tuple[int, datetime, float]], *, horizon: int, n_paths: int) -> None:
        self._run = (horizon, n_paths, datetime(2026, 4, 1, tzinfo=timezone.utc))
        self._rows = rows
        self._last_query = ""

    def execute(self, query: str, params: tuple[str]) -> None:
        self._last_query = query

    def fetchone(self) -> tuple[int, int, datetime]:
        return self._run

    def fetchall(self) -> list[tuple[int, datetime, float]]:
        return self._rows


def test_load_forecast_paths_rejects_incomplete_matrix() -> None:
    origin = datetime(2026, 4, 1, tzinfo=timezone.utc)
    rows = [
        (0, origin, 10.0),
        (1, origin, 20.0),
        # Missing path 1 for the second slot.
        (0, origin + timedelta(minutes=30), 11.0),
    ]

    with pytest.raises(RuntimeError, match="row count"):
        _load_forecast_paths(FakeCursor(rows, horizon=2, n_paths=2), "run-a")


def test_load_forecast_paths_rejects_sparse_complete_row_count() -> None:
    origin = datetime(2026, 4, 1, tzinfo=timezone.utc)
    rows = [
        (0, origin, 10.0),
        (1, origin, 20.0),
        (0, origin + timedelta(minutes=30), 11.0),
        # Row count is correct, but path 1 slot 1 is missing and path 0 has an extra slot.
        (0, origin + timedelta(minutes=60), 12.0),
    ]

    with pytest.raises(RuntimeError, match="incomplete|more than"):
        _load_forecast_paths(FakeCursor(rows, horizon=2, n_paths=2), "run-a")


def test_load_forecast_paths_returns_jpy_mwh_matrix() -> None:
    origin = datetime(2026, 4, 1, tzinfo=timezone.utc)
    rows = [
        (0, origin, 10.0),
        (1, origin, 20.0),
        (0, origin + timedelta(minutes=30), 11.0),
        (1, origin + timedelta(minutes=30), 21.0),
    ]

    paths, slot_starts = _load_forecast_paths(FakeCursor(rows, horizon=2, n_paths=2), "run-a")

    np.testing.assert_allclose(paths, np.array([[10_000.0, 11_000.0], [20_000.0, 21_000.0]]))
    assert slot_starts == [origin, origin + timedelta(minutes=30)]
