from datetime import datetime, timezone

import pytest

from lsm.runner import _load_forecast_paths


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def execute(self, *_args, **_kwargs):
        self.calls += 1

    def fetchone(self):
        return (2, 2, datetime(2026, 5, 1, tzinfo=timezone.utc))

    def fetchall(self):
        return self.rows


def test_load_forecast_paths_rejects_incomplete_grid():
    slot_0 = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    slot_1 = datetime(2026, 5, 1, 0, 30, tzinfo=timezone.utc)
    cur = FakeCursor(
        [
            (0, slot_0, 10.0),
            (1, slot_0, 11.0),
            (0, slot_1, 12.0),
        ]
    )

    with pytest.raises(RuntimeError, match="incomplete forecast_paths"):
        _load_forecast_paths(cur, "forecast-run")


def test_load_forecast_paths_rejects_duplicate_cells():
    slot_0 = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    slot_1 = datetime(2026, 5, 1, 0, 30, tzinfo=timezone.utc)
    cur = FakeCursor(
        [
            (0, slot_0, 10.0),
            (0, slot_0, 10.5),
            (0, slot_1, 12.0),
            (1, slot_1, 13.0),
        ]
    )

    with pytest.raises(RuntimeError, match="duplicate forecast_paths cell"):
        _load_forecast_paths(cur, "forecast-run")


def test_load_forecast_paths_returns_complete_matrix_in_jpy_mwh():
    slot_0 = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
    slot_1 = datetime(2026, 5, 1, 0, 30, tzinfo=timezone.utc)
    cur = FakeCursor(
        [
            (0, slot_0, 10.0),
            (1, slot_0, 11.0),
            (0, slot_1, 12.0),
            (1, slot_1, 13.0),
        ]
    )

    paths, slot_starts = _load_forecast_paths(cur, "forecast-run")

    assert slot_starts == [slot_0, slot_1]
    assert paths.tolist() == [
        [10_000.0, 12_000.0],
        [11_000.0, 13_000.0],
    ]
