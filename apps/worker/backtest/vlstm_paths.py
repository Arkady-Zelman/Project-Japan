"""Load VLSTM forecast_paths for a backtest window (M10C L5).

For each roll origin in the backtest, find the most recent forecast_run
posted before that origin's slot_start, and return the (P, S) forecast
paths matrix in JPY/kWh.

When no forecast_run is available for a given origin, returns None for
that slot — the LSMVLSTMStrategy falls back to stack-driven forecasts.

`forecast_paths` is keyed by (forecast_run_id, path_id, slot_start) — not
the non-existent (run_id, path_index, slot_ix) columns an earlier draft
queried, which made every lsm_vlstm load fail closed to stack.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import cast

import numpy as np

logger = logging.getLogger("backtest.vlstm_paths")

# Keep these identical to `strategies.DEFAULT_*`. Duplicated so this module
# can be imported (and its reshape helper unit-tested) without pulling the
# Numba LSM engine.
DEFAULT_LOOKAHEAD_SLOTS = 48
DEFAULT_ROLL_INTERVAL_SLOTS = 2


def reshape_forecast_path_rows(
    rows: list[tuple],
) -> np.ndarray | None:
    """Reshape (path_id, slot_start, price_jpy_kwh) rows to (P, S) JPY/kWh.

    Columns are ordered by first-seen `slot_start`. Paths with any missing
    slot are dropped so the LSM never sees a NaN-padded ensemble.
    """
    if not rows:
        return None
    slot_set: dict[object, int] = {}
    parsed: list[tuple[int, int, float]] = []
    max_path = 0
    for path_id, slot_start, price in rows:
        pid = int(path_id)
        max_path = max(max_path, pid)
        if slot_start not in slot_set:
            slot_set[slot_start] = len(slot_set)
        parsed.append((pid, slot_set[slot_start], float(price)))
    mat = np.full((max_path + 1, len(slot_set)), np.nan, dtype=np.float64)
    for pid, t_idx, price in parsed:
        mat[pid, t_idx] = price
    valid = ~np.isnan(mat).any(axis=1)
    mat = mat[valid]
    if mat.shape[0] == 0:
        return None
    return mat


def load_vlstm_paths_per_origin(
    area_id: str,
    slot_starts: list[datetime],
    *,
    lookahead_slots: int = DEFAULT_LOOKAHEAD_SLOTS,
    roll_interval_slots: int = DEFAULT_ROLL_INTERVAL_SLOTS,
) -> list[np.ndarray | None]:
    """Return forecast_paths matrices per LSM roll origin.

    Args:
        area_id: UUID of the area.
        slot_starts: full list of realised slot_start timestamps in the
            backtest window.
        lookahead_slots: number of half-hour slots in each forecast (= 48).
        roll_interval_slots: how often LSM rolls. Must match
            `strategies.DEFAULT_ROLL_INTERVAL_SLOTS` (2 = every hour) or
            most origins silently fall back to the stack model.

    Returns:
        List of (P, S) ndarrays in JPY/kWh, one per origin. Element is
        None when no forecast_run is available before that origin.
    """
    T = len(slot_starts)
    H = lookahead_slots
    origin_indices = list(range(0, T - H + 1, roll_interval_slots))
    out: list[np.ndarray | None] = [None] * len(origin_indices)
    if not origin_indices:
        return out

    from common.db import connect

    with connect() as conn, conn.cursor() as cur:
        for i, origin in enumerate(origin_indices):
            origin_ts = slot_starts[origin]
            # Latest forecast_run for this area posted at or before origin.
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

            cur.execute(
                """
                select path_id, slot_start, price_jpy_kwh
                from forecast_paths
                where forecast_run_id = %s
                  and slot_start >= %s
                order by slot_start, path_id
                """,
                (run_id, origin_ts),
            )
            rows = cur.fetchall()
            mat = reshape_forecast_path_rows(rows)
            if mat is not None and mat.shape[1] > H + 1:
                mat = mat[:, : H + 1]
            out[i] = mat
    return out
