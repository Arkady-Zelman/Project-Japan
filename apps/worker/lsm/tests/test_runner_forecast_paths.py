from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from lsm.runner import _load_forecast_paths


class FakeCursor:
    def __init__(self, rows: list[tuple[int, datetime, float]]) -> None:
        self._rows = rows
        self._calls = 0

    def execute(self, *_args: object, **_kwargs: object) -> None:
        return None

    def fetchone(self) -> tuple[int, int, datetime]:
        self._calls += 1
        return (2, 2, datetime(2026, 5, 15, tzinfo=UTC))

    def fetchall(self) -> list[tuple[int, datetime, float]]:
        self._calls += 1
        return self._rows


def test_load_forecast_paths_builds_complete_matrix() -> None:
    slot0 = datetime(2026, 5, 15, tzinfo=UTC)
    slot1 = slot0 + timedelta(minutes=30)
    cur = FakeCursor([
        (0, slot0, 10.0),
        (1, slot0, 11.0),
        (0, slot1, 12.0),
        (1, slot1, 13.0),
    ])

    paths, slots = _load_forecast_paths(cur, "forecast-run")

    assert slots == [slot0, slot1]
    np.testing.assert_array_equal(
        paths,
        np.array([[10_000.0, 12_000.0], [11_000.0, 13_000.0]]),
    )


def test_load_forecast_paths_rejects_missing_cells() -> None:
    slot0 = datetime(2026, 5, 15, tzinfo=UTC)
    slot1 = slot0 + timedelta(minutes=30)
    cur = FakeCursor([
        (0, slot0, 10.0),
        (1, slot0, 11.0),
        (0, slot1, 12.0),
    ])

    with pytest.raises(RuntimeError, match="incomplete forecast_paths"):
        _load_forecast_paths(cur, "forecast-run")


def test_load_forecast_paths_rejects_duplicate_cells() -> None:
    slot0 = datetime(2026, 5, 15, tzinfo=UTC)
    slot1 = slot0 + timedelta(minutes=30)
    cur = FakeCursor([
        (0, slot0, 10.0),
        (0, slot0, 10.0),
        (0, slot1, 12.0),
        (1, slot1, 13.0),
    ])

    with pytest.raises(RuntimeError, match="duplicate forecast_paths cell"):
        _load_forecast_paths(cur, "forecast-run")
