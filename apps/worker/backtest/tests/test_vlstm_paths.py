from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from backtest import vlstm_paths


class _FakeCursor:
    def __init__(self, rows_by_origin: dict[datetime, list[tuple[int, datetime, float]]]) -> None:
        self.rows_by_origin = rows_by_origin
        self.queries: list[str] = []
        self._one: tuple[str] | None = None
        self._many: list[tuple[int, datetime, float]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, query: str, args: tuple[Any, ...]) -> None:
        self.queries.append(query)
        if "from forecast_runs" in query:
            self._one = ("run-1",)
            self._many = []
            return
        if "from forecast_paths" in query:
            _run_id, origin_ts, _horizon_end = args
            self._one = None
            self._many = self.rows_by_origin.get(origin_ts, [])
            return
        raise AssertionError(f"unexpected query: {query}")

    def fetchone(self) -> tuple[str] | None:
        return self._one

    def fetchall(self) -> list[tuple[int, datetime, float]]:
        return self._many


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


def test_load_vlstm_paths_uses_forecast_path_schema_and_matches_roll_grid(monkeypatch) -> None:
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    slots = [origin + timedelta(minutes=30 * i) for i in range(8)]
    rows_by_origin = {
        slots[0]: [
            (0, slots[0], 10.0),
            (0, slots[1], 11.0),
            (0, slots[2], 12.0),
            (0, slots[3], 13.0),
            (1, slots[0], 20.0),
            (1, slots[1], 21.0),
            (1, slots[2], 22.0),
            (1, slots[3], 23.0),
        ],
        # Partial future horizon: the loader should keep the path and pad the
        # missing tail with the last known price so rolling LSM can still run.
        slots[2]: [
            (0, slots[2], 30.0),
            (0, slots[3], 31.0),
        ],
    }
    cursor = _FakeCursor(rows_by_origin)
    monkeypatch.setattr(vlstm_paths, "connect", lambda: _FakeConn(cursor))

    out = vlstm_paths.load_vlstm_paths_per_origin(
        "area-id",
        slots,
        lookahead_slots=4,
        roll_interval_slots=2,
    )

    assert len(out) == 3
    assert out[0] is not None
    assert out[0].shape == (2, 5)
    np.testing.assert_allclose(out[0][0], [10.0, 11.0, 12.0, 13.0, 13.0])
    np.testing.assert_allclose(out[0][1], [20.0, 21.0, 22.0, 23.0, 23.0])
    assert out[1] is not None
    np.testing.assert_allclose(out[1][0], [30.0, 31.0, 31.0, 31.0, 31.0])
    assert out[2] is None

    query_text = "\n".join(cursor.queries)
    assert "forecast_run_id" in query_text
    assert "path_id" in query_text
    assert "slot_start" in query_text
    assert "where run_id" not in query_text
    assert "path_index" not in query_text
    assert "slot_ix" not in query_text
