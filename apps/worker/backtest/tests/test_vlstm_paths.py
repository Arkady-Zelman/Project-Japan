from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from backtest import vlstm_paths


class FakeCursor:
    def __init__(self, path_rows: list[tuple[int, datetime, float]]) -> None:
        self.path_rows = path_rows
        self.rows: list[tuple[Any, ...]] = []
        self.queries: list[str] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...]) -> None:
        self.queries.append(query)
        if "from forecast_runs" in query:
            self.rows = [("run-1",)]
            return

        assert "from forecast_paths" in query
        run_id, start, end = params
        assert run_id == "run-1"
        self.rows = [
            (path_id, slot_start, price)
            for path_id, slot_start, price in self.path_rows
            if start <= slot_start < end
        ]

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


def test_load_vlstm_paths_uses_schema_columns_and_roll_alignment(monkeypatch) -> None:
    start = datetime(2026, 4, 1, tzinfo=UTC)
    slot_starts = [start + timedelta(minutes=30 * i) for i in range(8)]
    path_rows = [
        (path_id, slot_start, float(path_id * 100 + slot_ix))
        for path_id in range(2)
        for slot_ix, slot_start in enumerate(slot_starts[:6])
    ]
    cursor = FakeCursor(path_rows)
    monkeypatch.setattr(vlstm_paths, "connect", lambda: FakeConnection(cursor))

    loaded = vlstm_paths.load_vlstm_paths_per_origin(
        "area-1",
        slot_starts,
        lookahead_slots=4,
        roll_interval_slots=2,
    )

    assert len(loaded) == 3
    assert loaded[0] is not None
    assert loaded[1] is not None
    assert loaded[2] is not None
    assert loaded[0].shape == (2, 5)
    assert loaded[1].shape == (2, 4)
    assert loaded[2].shape == (2, 2)
    assert loaded[1][0, 0] == 2.0
    assert loaded[1][1, 0] == 102.0

    forecast_path_queries = [q for q in cursor.queries if "from forecast_paths" in q]
    assert forecast_path_queries
    for query in forecast_path_queries:
        assert "forecast_run_id" in query
        assert "path_id" in query
        assert "slot_start" in query
        assert "where run_id" not in query
        assert "path_index" not in query
        assert "slot_ix" not in query
