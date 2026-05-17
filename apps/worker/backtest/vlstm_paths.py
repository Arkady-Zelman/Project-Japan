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

            # Pull forecast rows aligned to this rolling origin. The table stores
            # absolute slot_start timestamps, not per-run slot indices.
            cur.execute(
                """
                select path_id, slot_start, price_jpy_kwh
                from forecast_paths
                where forecast_run_id = %s
                  and slot_start >= %s
                  and slot_start < %s
                order by path_id, slot_start
                """,
                (run_id, origin_ts, origin_ts + timedelta(minutes=30 * H)),
            )
            rows = cur.fetchall()
            if not rows:
                out[i] = None
                continue

            slot_values = sorted({r[1] for r in rows})
            slot_to_ix = {slot: ix for ix, slot in enumerate(slot_values)}
            path_values = sorted({int(r[0]) for r in rows})
            path_to_ix = {path_id: ix for ix, path_id in enumerate(path_values)}
            mat = np.full((len(path_values), len(slot_values)), np.nan, dtype=np.float64)
            for r in rows:
                mat[path_to_ix[int(r[0])], slot_to_ix[r[1]]] = float(r[2])
            # Drop any path rows with NaN (incomplete).
            valid = ~np.isnan(mat).any(axis=1)
            mat = mat[valid]
            if mat.shape[0] == 0:
                out[i] = None
                continue
            out[i] = mat
    return out
