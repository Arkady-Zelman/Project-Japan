from datetime import UTC, datetime, timedelta

import numpy as np

from backtest import vlstm_paths


class _FakeCursor:
    def __init__(self, base: datetime) -> None:
        self.base = base
        self._one = None
        self._many = []
        self.sql: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self.sql.append(sql)
        if "from forecast_runs" in sql:
            self._one = ("run-1",)
            self._many = []
            return

        origin = params[1]
        origin_slot = int((origin - self.base).total_seconds() // (30 * 60))
        self._one = None
        self._many = [
            (
                path_id,
                origin + timedelta(minutes=30 * slot_ix),
                path_id * 100.0 + origin_slot * 10.0 + slot_ix,
            )
            for path_id in range(2)
            for slot_ix in range(4)
        ]

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def cursor(self):
        return self._cursor


def test_loader_uses_forecast_paths_schema_and_origin_relative_slots(monkeypatch) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    cursor = _FakeCursor(base)
    monkeypatch.setattr(vlstm_paths, "connect", lambda: _FakeConnection(cursor))

    slot_starts = [base + timedelta(minutes=30 * i) for i in range(10)]
    loaded = vlstm_paths.load_vlstm_paths_per_origin(
        "area-id",
        slot_starts,
        lookahead_slots=4,
        roll_interval_slots=2,
    )

    assert len(loaded) == 4
    for matrix in loaded:
        assert matrix is not None
        assert matrix.shape == (2, 4)

    assert np.allclose(loaded[1][0], np.array([20.0, 21.0, 22.0, 23.0]))
    path_sql = "\n".join(cursor.sql).lower()
    assert "forecast_run_id" in path_sql
    assert "path_id" in path_sql
    assert "slot_start" in path_sql
    assert "path_index" not in path_sql
    assert "slot_ix" not in path_sql
    assert "where run_id" not in path_sql
