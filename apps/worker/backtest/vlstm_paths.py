"""Load VLSTM forecast_paths for a backtest window (M10C L5).

For each roll origin in the backtest, find the most recent forecast_run
posted before that origin's slot_start, and return the (P, H+1) forecast
paths matrix in JPY/kWh.

When no forecast_run is available for a given origin, returns None for
that slot — the LSMVLSTMStrategy falls back to stack-driven forecasts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import cast

import numpy as np

from common.db import connect

logger = logging.getLogger("backtest.vlstm_paths")


def load_vlstm_paths_per_origin(
    area_id: str,
    slot_starts: list[datetime],
    *,
    lookahead_slots: int = 48,
    roll_interval_slots: int = 2,
) -> list[np.ndarray | None]:
    """Return forecast_paths matrices per LSM roll origin.

    Args:
        area_id: UUID of the area.
        slot_starts: full list of realised slot_start timestamps in the
            backtest window.
        lookahead_slots: number of half-hour slots in each forecast (= 48).
        roll_interval_slots: how often LSM rolls (= 2, i.e. every 1h).

    Returns:
        List of (P, lookahead_slots+1) ndarrays in JPY/kWh, one per origin.
        Element is None when no forecast_run is available before that
        origin's slot_start.
    """
    T = len(slot_starts)
    H = lookahead_slots
    origin_indices = list(range(0, T - H + 1, roll_interval_slots))
    out: list[np.ndarray | None] = [None] * len(origin_indices)
    if not origin_indices:
        return out

    with connect() as conn, conn.cursor() as cur:
        for i, origin in enumerate(origin_indices):
            origin_ts = slot_starts[origin]
            # Latest forecast_run for this area posted BEFORE the origin slot.
            cur.execute(
                """
                select id::text from forecast_runs
                where area_id = %s and forecast_origin <= %s
                order by forecast_origin desc limit 1
                """,
                (area_id, origin_ts),
            )
            row = cur.fetchone()
            if not row:
                out[i] = None
                continue
            run_id = cast(str, row[0])

            horizon_end = origin_ts + timedelta(minutes=30 * H)
            # Pull forecast rows using the persisted schema. Older code used
            # synthetic path_index/slot_ix columns that do not exist.
            cur.execute(
                """
                select path_id, slot_start, price_jpy_kwh
                from forecast_paths
                where forecast_run_id = %s
                  and slot_start >= %s
                  and slot_start < %s
                order by path_id, slot_start
                """,
                (run_id, origin_ts, horizon_end),
            )
            rows = cur.fetchall()
            if not rows:
                out[i] = None
                continue

            # Reshape into (P, H+1). forecast_paths stores H executable slots;
            # run_lsm expects an extra post-horizon price anchor, so we append
            # the last available price per path.
            by_path: dict[int, np.ndarray] = {}
            for path_id, slot_start, price_kwh in rows:
                path_ix = int(path_id)
                arr = by_path.setdefault(path_ix, np.full(H + 1, np.nan, dtype=np.float64))
                slot_ix = _slot_offset(origin_ts, slot_start)
                if 0 <= slot_ix < H:
                    arr[slot_ix] = float(price_kwh)

            complete_paths: list[np.ndarray] = []
            for arr in by_path.values():
                if np.isnan(arr[0]):
                    continue
                for j in range(1, H + 1):
                    if np.isnan(arr[j]):
                        arr[j] = arr[j - 1]
                complete_paths.append(arr)

            if not complete_paths:
                out[i] = None
                continue
            out[i] = np.vstack(complete_paths)
    return out


def _slot_offset(origin: datetime, slot_start: datetime) -> int:
    """Return half-hour offset from origin, tolerating naive/aware mixing."""
    if origin.tzinfo is None and slot_start.tzinfo is not None:
        origin = origin.replace(tzinfo=slot_start.tzinfo)
    elif origin.tzinfo is not None and slot_start.tzinfo is None:
        slot_start = slot_start.replace(tzinfo=origin.tzinfo)
    return int(round((slot_start - origin).total_seconds() / (30 * 60)))
