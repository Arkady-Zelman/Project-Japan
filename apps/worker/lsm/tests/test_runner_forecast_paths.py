from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lsm.runner import _load_forecast_paths


class FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.query_count = 0

    def execute(self, *_args: object) -> None:
        self.query_count += 1

    def fetchone(self) -> tuple[int, int, datetime]:
        return (2, 2, datetime(2026, 6, 10, tzinfo=UTC))

    def fetchall(self) -> list[tuple]:
        return self.rows


def test_load_forecast_paths_requires_complete_matrix() -> None:
    slot0 = datetime(2026, 6, 10, 0, 0, tzinfo=UTC)
    slot1 = slot0 + timedelta(minutes=30)
    rows = [
        (0, slot0, 10.0),
        (1, slot0, 20.0),
        (0, slot1, 30.0),
    ]

    with pytest.raises(RuntimeError, match="incomplete forecast_paths"):
        _load_forecast_paths(FakeCursor(rows), "forecast-run-id")


def test_load_forecast_paths_builds_complete_price_matrix() -> None:
    slot0 = datetime(2026, 6, 10, 0, 0, tzinfo=UTC)
    slot1 = slot0 + timedelta(minutes=30)
    rows = [
        (0, slot0, 10.0),
        (1, slot0, 20.0),
        (0, slot1, 30.0),
        (1, slot1, 40.0),
    ]

    paths_mwh, slot_starts = _load_forecast_paths(FakeCursor(rows), "forecast-run-id")

    assert slot_starts == [slot0, slot1]
    assert paths_mwh.tolist() == [
        [10_000.0, 30_000.0],
        [20_000.0, 40_000.0],
    ]
