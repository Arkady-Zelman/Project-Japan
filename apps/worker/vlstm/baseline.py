"""Naive AR(1) per-area baseline for the M6 STOP gate.

Per BUILD_SPEC §12 M6: VLSTM must beat AR(1) on ≥6 of 9 areas at the 24h
horizon (slot index 47 in the 48-step forecast, since slots are
half-hourly). AR(1) on raw price is the simplest defensible "naive
ARIMA" baseline — one persistence coefficient per area, fit on the same
training window the VLSTM saw.

The 24h-horizon RMSE of an AR(1) on JEPX is roughly the standard deviation
of price increments at that horizon, which is non-trivial in spike-prone
areas like TK. So the bar isn't artificially low.

Public API:
- `fit_ar1(prices: np.ndarray) -> tuple[float, float]`  → (c, phi)
- `forecast_ar1(c, phi, last_price, horizon=48) -> np.ndarray`
- `evaluate_baseline(area_codes, gate_start, gate_end) -> dict[area_code, dict]`
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from common.db import connect

from .data import AREA_INDEX, SLOT_MIN
from .models import HORIZON_SLOTS, AreaCode

logger = logging.getLogger("vlstm.baseline")


def fit_ar1(prices: np.ndarray) -> tuple[float, float]:
    """Closed-form AR(1) fit: y_t = c + phi*y_{t-1} + e.

    Uses np.polyfit on (y_{t-1}, y_t) — 2-parameter linear regression. We
    bypass statsmodels' ARIMA wrapper because (a) we already have a
    statsmodels dep but importing ARIMA costs ~500ms cold-start per call,
    and (b) the closed form is two lines that nobody can mis-tune.
    """
    if len(prices) < 2:
        return (float(np.mean(prices)) if len(prices) else 0.0, 0.0)
    y = prices[1:]
    x = prices[:-1]
    phi, c = np.polyfit(x, y, 1)   # slope, intercept
    return float(c), float(phi)


def forecast_ar1(
    c: float, phi: float, last_price: float, horizon: int = HORIZON_SLOTS,
) -> np.ndarray:
    """48-step recursive forecast: y_{t+1} = c + phi*y_t."""
    out = np.empty(horizon, dtype=float)
    p = last_price
    for i in range(horizon):
        p = c + phi * p
        out[i] = p
    return out


def _load_prices(
    area_id: str, start: datetime, end: datetime,
) -> pd.Series:
    """Pull jepx day-ahead prices for an area, indexed by slot_start."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select slot_start, price_jpy_kwh from jepx_spot_prices
            where area_id=%s and auction_type='day_ahead'
              and slot_start >= %s and slot_start < %s
              and price_jpy_kwh is not null
            order by slot_start
            """,
            (area_id, start, end),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series(
        data=[float(r[1]) for r in rows],
        index=pd.DatetimeIndex([r[0] for r in rows], tz="UTC"),
    )
    return s


def evaluate_baseline(
    area_codes: tuple[AreaCode, ...] | None = None,
    *,
    train_start: datetime,
    gate_start: datetime,
    gate_end: datetime,
) -> dict[str, dict]:
    """Fit AR(1) per area on `[train_start, gate_start)` and evaluate RMSE
    on rolling 48-step forecasts originated every 24h within
    `[gate_start, gate_end)`. Returns per-area metrics.

    Output keys per area:
        rmse_per_horizon: list of 48 floats (RMSE at each slot ahead)
        rmse_at_24h:     scalar (slot index 47, the M6 gate metric)
        n_origins:       number of forecast origins evaluated
    """
    if area_codes is None:
        area_codes = tuple(AREA_INDEX.keys())   # type: ignore[assignment]

    out: dict[str, dict] = {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select code, id::text from areas where code != 'SYS'")
        area_id_by_code = {r[0]: r[1] for r in cur.fetchall()}

    for code in area_codes:
        area_id = area_id_by_code[code]
        train = _load_prices(area_id, train_start, gate_start)
        eval_ = _load_prices(area_id, gate_start, gate_end + timedelta(minutes=SLOT_MIN * HORIZON_SLOTS))
        if len(train) < 100 or len(eval_) < HORIZON_SLOTS + 24:
            logger.warning("%s: insufficient data — train=%d eval=%d", code, len(train), len(eval_))
            out[code] = {"skipped": True, "n_train": len(train), "n_eval": len(eval_)}
            continue

        c, phi = fit_ar1(train.to_numpy())

        # Roll a forecast every 24h (= 48 slots) within the gate window.
        squared_errors_per_horizon = [list() for _ in range(HORIZON_SLOTS)]
        n_origins = 0
        origin_step = HORIZON_SLOTS
        origins = pd.date_range(
            start=gate_start, end=gate_end, freq=f"{SLOT_MIN}min", inclusive="left"
        )
        for i, origin in enumerate(origins):
            if i % origin_step != 0:
                continue
            origin_ts = origin.to_pydatetime()
            # Need the price at `origin - 30min` (last observed) and the
            # next 48 prices for evaluation.
            try:
                last_price = float(eval_.loc[eval_.index < origin].iloc[-1])
            except (IndexError, KeyError):
                # Try training window edge.
                try:
                    last_price = float(train.iloc[-1])
                except IndexError:
                    continue
            future_idx = pd.date_range(
                start=origin, periods=HORIZON_SLOTS, freq=f"{SLOT_MIN}min", tz="UTC"
            )
            actual = eval_.reindex(future_idx)
            if actual.isna().any():
                continue
            forecast = forecast_ar1(c, phi, last_price)
            err = (forecast - actual.to_numpy()) ** 2
            for h in range(HORIZON_SLOTS):
                squared_errors_per_horizon[h].append(float(err[h]))
            n_origins += 1

        rmse_per_h = [
            math.sqrt(float(np.mean(e))) if e else float("nan")
            for e in squared_errors_per_horizon
        ]
        out[code] = {
            "c": c, "phi": phi,
            "rmse_per_horizon": rmse_per_h,
            "rmse_at_24h": rmse_per_h[HORIZON_SLOTS - 1],
            "n_origins": n_origins,
            "n_train": int(len(train)),
        }
        logger.info(
            "%s: AR(1) c=%.3f phi=%.3f rmse@24h=%.3f n_origins=%d",
            code, c, phi, rmse_per_h[HORIZON_SLOTS - 1], n_origins,
        )

    return out
