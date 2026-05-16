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

from .strategies import DEFAULT_ROLL_INTERVAL_SLOTS

logger = logging.getLogger("backtest.vlstm_paths")


def load_vlstm_paths_per_origin(
    area_id: str,
    slot_starts: list[datetime],
    *,
    lookahead_slots: int = 48,
    roll_interval_slots: int = DEFAULT_ROLL_INTERVAL_SLOTS,
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

            horizon_end = origin_ts + timedelta(minutes=30 * (H + 1))
            # Pull schema-native forecast_path rows for the remaining horizon
            # from this roll origin. Older runs may have fewer remaining slots;
            # LSMVLSTMStrategy pads those curves with the last available price.
            cur.execute(
                """
                select path_id, slot_start, price_jpy_kwh
                from forecast_paths
                where forecast_run_id = %s
                  and slot_start >= %s
                  and slot_start < %s
                order by slot_start, path_id
                """,
                (run_id, origin_ts, horizon_end),
            )
            rows = cur.fetchall()
            if not rows:
                out[i] = None
                continue
            # Reshape into (P, H+1).
            max_path = max(int(r[0]) for r in rows)
            P = max_path + 1
            slot_ix_by_start: dict[datetime, int] = {}
            for _, slot_start, _ in rows:
                if slot_start not in slot_ix_by_start:
                    slot_ix_by_start[slot_start] = len(slot_ix_by_start)
            S = len(slot_ix_by_start)
            mat = np.full((P, S), np.nan, dtype=np.float64)
            for path_id, slot_start, price_kwh in rows:
                mat[int(path_id), slot_ix_by_start[slot_start]] = float(price_kwh)
            # Drop any path rows with NaN (incomplete).
            valid = ~np.isnan(mat).any(axis=1)
            mat = mat[valid]
            if mat.shape[0] == 0:
                out[i] = None
                continue
            out[i] = mat
    return out
