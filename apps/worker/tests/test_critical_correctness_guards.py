from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib
from pathlib import Path
import sys
import types

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]


def _read_repo_file(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_retention_does_not_delete_canonical_history_or_forecast_runs() -> None:
    modal_app = _read_repo_file("apps/worker/modal_app.py").lower()

    forbidden_fragments = [
        "truncate table",
        "delete from forecast_runs",
        "delete from jepx_spot_prices",
        "delete from demand_actuals",
        "delete from generation_mix_actuals",
        "delete from weather_obs",
        "delete from regime_states",
        "delete from stack_curves",
        "delete from stack_clearing_prices",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in modal_app

    assert "delete from forecast_paths" in modal_app
    assert "def prune_nightly" in modal_app
    assert "return prune_forecast_paths.local" in modal_app


def test_public_bos_demo_uses_fractional_soc_bounds() -> None:
    route = _read_repo_file("apps/web/src/app/api/bos-strategy/route.ts")

    assert "soc_min_pct: 0.10" in route
    assert "soc_max_pct: 0.90" in route
    assert "soc_min_pct: 10" not in route
    assert "soc_max_pct: 90" not in route


class _FakeCursor:
    def __init__(self, origin: datetime) -> None:
        self.origin = origin
        self._fetchone: tuple[str] | None = None
        self._fetchall: list[tuple[int, datetime, float]] = []
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.queries.append((sql, params))
        if "from forecast_runs" in sql:
            self._fetchone = ("run-1",)
            return

        assert "path_index" not in sql
        assert "slot_ix" not in sql
        assert "run_id =" not in sql
        assert "forecast_run_id = %s" in sql
        assert "slot_start >= %s" in sql

        run_id, start, end = params
        assert run_id == "run-1"
        assert start == self.origin
        assert end == self.origin + timedelta(minutes=90)
        self._fetchall = [
            (0, self.origin, 10.0),
            (1, self.origin, 20.0),
            (0, self.origin + timedelta(minutes=30), 11.0),
            (1, self.origin + timedelta(minutes=30), 21.0),
            (0, self.origin + timedelta(minutes=60), 12.0),
            (1, self.origin + timedelta(minutes=60), 22.0),
        ]

    def fetchone(self) -> tuple[str] | None:
        return self._fetchone

    def fetchall(self) -> list[tuple[int, datetime, float]]:
        return self._fetchall


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


def test_vlstm_loader_uses_current_forecast_paths_schema(monkeypatch) -> None:
    origin = datetime(2026, 7, 6, tzinfo=UTC)
    cursor = _FakeCursor(origin)
    fake_common_db = types.ModuleType("common.db")
    fake_common_db.connect = lambda: _FakeConnection(cursor)
    monkeypatch.setitem(sys.modules, "common.db", fake_common_db)

    sys.modules.pop("backtest.vlstm_paths", None)
    vlstm_paths = importlib.import_module("backtest.vlstm_paths")
    monkeypatch.setattr(vlstm_paths, "connect", lambda: _FakeConnection(cursor))

    paths = vlstm_paths.load_vlstm_paths_per_origin(
        "area-1",
        [origin, origin + timedelta(minutes=30), origin + timedelta(minutes=60)],
        lookahead_slots=2,
    )

    assert len(paths) == 1
    assert paths[0] is not None
    np.testing.assert_allclose(paths[0], np.array([[10.0, 11.0, 12.0], [20.0, 21.0, 22.0]]))

