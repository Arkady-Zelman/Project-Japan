"""Load VLSTM forecast_paths for a backtest window (M10C L5).

For each roll origin in the backtest, find the most recent forecast_run
posted before that origin's slot_start, and return the (P, H+1) forecast
paths matrix in JPY/kWh.

When no forecast_run is available for a given origin, returns None for
that slot — the LSMVLSTMStrategy falls back to stack-driven forecasts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import cast

import numpy as np

from common.db import connect

logger = logging.getLogger("backtest.vlstm_paths")


def load_vlstm_paths_per_origin(
    area_id: str,
    slot_starts: list[datetime],
    *,
    lookahead_slots: int = 48,
    roll_interval_slots: int = 24,
) -> list[np.ndarray | None]:
    """Return forecast_paths matrices per LSM roll origin.

    Args:
        area_id: UUID of the area.
        slot_starts: full list of realised slot_start timestamps in the
            backtest window.
        lookahead_slots: number of half-hour slots in each forecast (= 48).
        roll_interval_slots: how often LSM rolls (= 24, i.e. every 12h).

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

            # Pull all (path_index, slot_ix, price_jpy_kwh) rows for that run.
            cur.execute(
                """
                select path_index, slot_ix, price_jpy_kwh
                from forecast_paths
                where run_id = %s and slot_ix < %s
                """,
                (run_id, H + 1),
            )
            rows = cur.fetchall()
            if not rows:
                out[i] = None
                continue
            # Reshape into (P, H+1).
            max_path = max(int(r[0]) for r in rows)
            max_slot = max(int(r[1]) for r in rows)
            P = max_path + 1
            S = max_slot + 1
            mat = np.full((P, S), np.nan, dtype=np.float64)
            for r in rows:
                mat[int(r[0]), int(r[1])] = float(r[2])
            # Drop any path rows with NaN (incomplete).
            valid = ~np.isnan(mat).any(axis=1)
            mat = mat[valid]
            if mat.shape[0] == 0:
                out[i] = None
                continue
            out[i] = mat
    return out
