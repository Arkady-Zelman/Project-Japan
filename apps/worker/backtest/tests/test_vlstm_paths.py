from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from backtest import vlstm_paths


class FakeCursor:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.params: list[tuple] = []
        self._fetchone_results: list[tuple[str] | None] = [("run-a",)]
        origin = datetime(2026, 4, 1, tzinfo=timezone.utc)
        self._fetchall_results = [[
            (0, origin, 10.0),
            (1, origin, 20.0),
            (0, origin + timedelta(minutes=30), 11.0),
            (1, origin + timedelta(minutes=30), 21.0),
            (0, origin + timedelta(minutes=60), 12.0),
            (1, origin + timedelta(minutes=60), 22.0),
        ]]

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: tuple) -> None:
        self.queries.append(query)
        self.params.append(params)

    def fetchone(self) -> tuple[str] | None:
        return self._fetchone_results.pop(0)

    def fetchall(self) -> list[tuple[int, datetime, float]]:
        return self._fetchall_results.pop(0)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


def test_load_vlstm_paths_uses_forecast_paths_schema(monkeypatch) -> None:
    cursor = FakeCursor()
    monkeypatch.setattr(vlstm_paths, "connect", lambda: FakeConnection(cursor))

    origin = datetime(2026, 4, 1, tzinfo=timezone.utc)
    result = vlstm_paths.load_vlstm_paths_per_origin(
        "area-a",
        [origin + timedelta(minutes=30 * i) for i in range(3)],
        lookahead_slots=2,
        roll_interval_slots=2,
    )

    assert len(result) == 1
    assert result[0] is not None
    np.testing.assert_allclose(result[0], np.array([[10.0, 11.0, 12.0], [20.0, 21.0, 22.0]]))

    path_query = cursor.queries[1]
    assert "forecast_run_id" in path_query
    assert "path_id" in path_query
    assert "slot_start" in path_query
    assert "where run_id" not in path_query.lower()
    assert "path_index" not in path_query
    assert "slot_ix" not in path_query
