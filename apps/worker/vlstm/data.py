"""Feature builder for the VLSTM forecaster.

Per BUILD_SPEC §7.5 step 2: five feature blocks (autoregressive, calendar,
fundamentals, exogenous, regime). For one training/inference example at
origin `t`:

- Lookback window: 168 half-hour slots ending at t (3.5 days).
- Per-slot feature vector: 27 channels covering all five blocks.
- Forecast target (training only): log price at slots t+1..t+48 (24h ahead).

The 27-channel layout (per slot in the lookback):
  ch 0           log(price_jpy_kwh)            -- AR
  ch 1           log(stack_kwh)                -- fundamental baseline
  ch 2..3        sin/cos(hour_of_day * 2π/24)  -- calendar
  ch 4..5        sin/cos(dow * 2π/7)
  ch 6           is_holiday                    (0 or 1)
  ch 7..10       holiday_cat one-hot           (national, obon, newyear, goldenweek)
  ch 11          demand_norm                   (demand / area_mean)
  ch 12..16      genmix shares                 (vre, nuclear, lng, coal, hydro)
  ch 17..19      weather                       (temp_c, wind_mps, ghi_w_m2)
  ch 20..23      fuels + fx                    (log jkm, log coal, log brent, usdjpy)
  ch 24..26      regime probabilities          (p_base, p_spike, p_drop)

Bulk-fetch pattern mirrors `stack/build_curve._load_area_cache`: one query
per (area, table), then per-slot lookups happen in memory. The Tokyo
pooler is intolerant of per-slot DB roundtrips at 168 × 9 areas scale.

Public API:
- `build_area_cache(cur, area_id, area_code, start, end)` -> _AreaCache
- `build_feature_window(cache, origin, with_target=True)` -> FeatureWindow
- `build_training_examples(start, end, areas, stride=4)` -> iterator
- `build_inference_window(area_code, origin=None)` -> FeatureWindow
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import cast

import numpy as np
import pandas as pd
import psycopg

from common.db import connect

from .models import (
    HORIZON_SLOTS,
    LOOKBACK_SLOTS,
    AreaCode,
    FeatureWindow,
)

logger = logging.getLogger("vlstm.data")

N_FEATURES_PER_SLOT = 27          # see module docstring; tracked separately from N_FEATURES.

# Area code → embedding index. Stable order so model checkpoints survive code changes.
AREA_INDEX: dict[AreaCode, int] = {
    "TK": 0, "HK": 1, "TH": 2, "CB": 3, "HR": 4,
    "KS": 5, "CG": 6, "SK": 7, "KY": 8,
}
HOLIDAY_CATEGORIES = ("national", "obon", "newyear", "goldenweek")
SLOT_MIN = 30                     # half-hour slots throughout JEPX-Storage.


@dataclass
class _AreaCache:
    """All inputs cached for one area + window. Per-slot lookups happen in memory."""

    area_id: str
    area_code: AreaCode
    start: datetime
    end: datetime
    # Per-slot scalars, indexed by slot_start UTC datetime.
    price_kwh: dict[datetime, float] = field(default_factory=dict)
    stack_kwh: dict[datetime, float] = field(default_factory=dict)
    demand_mw: dict[datetime, float] = field(default_factory=dict)
    # Per-slot fuel-share dicts (vre, nuclear, lng, coal, hydro keys).
    genmix: dict[datetime, dict[str, float]] = field(default_factory=dict)
    # Per-slot weather (temp, wind, ghi). May be None per slot.
    weather: dict[datetime, tuple[float | None, float | None, float | None]] = field(
        default_factory=dict
    )
    # Per-slot regime probabilities (p_base, p_spike, p_drop).
    regime: dict[datetime, tuple[float, float, float]] = field(default_factory=dict)
    # Time-series fuels + FX (sorted ascending). Lookup via "latest ≤ slot".
    fuel_history: dict[str, list[tuple[datetime, float]]] = field(default_factory=dict)
    fx_history: list[tuple[datetime, float]] = field(default_factory=list)
    # Holiday metadata: date → set of category strings.
    holidays: dict[date, set[str]] = field(default_factory=dict)
    # Area-mean demand (for normalization). Computed once at cache build.
    demand_mean: float = 0.0


# ---------------------------------------------------------------------------
# Bulk loaders
# ---------------------------------------------------------------------------


def build_area_cache(
    cur: psycopg.Cursor,
    area_id: str,
    area_code: AreaCode,
    start: datetime,
    end: datetime,
) -> _AreaCache:
    """One bulk fetch per (area, input table). Returns an in-memory cache."""
    cache = _AreaCache(area_id=area_id, area_code=area_code, start=start, end=end)

    # JEPX prices and stack clearing prices fetched SEPARATELY. Joining
    # them at the cache level would mean horizon slots (no realised JEPX
    # price yet) have no cached stack — but inference needs stack for the
    # forecast horizon to reconstruct prices. Per-slot lookups in
    # `_slot_features` and `build_feature_window` already require both.
    cur.execute(
        """
        select slot_start, price_jpy_kwh from jepx_spot_prices
        where area_id=%s and auction_type='day_ahead'
          and slot_start >= %s and slot_start < %s
          and price_jpy_kwh is not null and price_jpy_kwh > 0
        """,
        (area_id, start, end),
    )
    for ts, price in cur.fetchall():
        cache.price_kwh[ts] = float(price)
    cur.execute(
        """
        select slot_start, modelled_price_jpy_mwh from stack_clearing_prices
        where area_id=%s and slot_start >= %s and slot_start < %s
          and modelled_price_jpy_mwh is not null and modelled_price_jpy_mwh > 0
        """,
        (area_id, start, end),
    )
    for ts, stack_jpy_mwh in cur.fetchall():
        cache.stack_kwh[ts] = float(stack_jpy_mwh) / 1000.0

    # Demand actuals.
    cur.execute(
        """
        select slot_start, demand_mw from demand_actuals
        where area_id=%s and slot_start >= %s and slot_start < %s
          and demand_mw is not null
        """,
        (area_id, start, end),
    )
    demand_vals = []
    for ts, mw in cur.fetchall():
        v = float(mw)
        cache.demand_mw[ts] = v
        demand_vals.append(v)
    cache.demand_mean = float(np.mean(demand_vals)) if demand_vals else 1.0

    # Generation mix — collapse fuel codes into 5 broad bins. Fuel-type codes
    # come from migration 001 and are confirmed against the live DB:
    #   solar, wind, nuclear, lng_ccgt, lng_steam, coal, oil, hydro,
    #   pumped_storage, biomass, geothermal, battery
    _VRE = {"solar", "wind"}
    _NUCLEAR = {"nuclear"}
    _LNG = {"lng_ccgt", "lng_steam"}
    _COAL = {"coal"}
    _HYDRO = {"hydro", "pumped_storage"}
    cur.execute(
        """
        select m.slot_start, ft.code, m.output_mw
        from generation_mix_actuals m
        join fuel_types ft on ft.id = m.fuel_type_id
        where m.area_id=%s and m.slot_start >= %s and m.slot_start < %s
          and m.output_mw is not null
        """,
        (area_id, start, end),
    )
    gm_acc: dict[datetime, dict[str, float]] = {}
    for ts, code, mw in cur.fetchall():
        v = float(mw)
        d = gm_acc.setdefault(
            ts, {"vre": 0.0, "nuclear": 0.0, "lng": 0.0, "coal": 0.0, "hydro": 0.0}
        )
        if code in _VRE:
            d["vre"] += v
        elif code in _NUCLEAR:
            d["nuclear"] += v
        elif code in _LNG:
            d["lng"] += v
        elif code in _COAL:
            d["coal"] += v
        elif code in _HYDRO:
            d["hydro"] += v
    # Convert each slot's bins to shares of total.
    for ts, bins in gm_acc.items():
        total = sum(bins.values())
        if total > 0:
            cache.genmix[ts] = {k: v / total for k, v in bins.items()}

    # Weather (forecast_horizon_h=0 = actuals). Optional per slot.
    cur.execute(
        """
        select ts, temp_c, wind_mps, ghi_w_m2 from weather_obs
        where area_id=%s and ts >= %s and ts < %s and forecast_horizon_h=0
        """,
        (area_id, start, end),
    )
    for ts, t, w, g in cur.fetchall():
        cache.weather[ts] = (
            float(t) if t is not None else None,
            float(w) if w is not None else None,
            float(g) if g is not None else None,
        )

    # Regime states from the latest active VLSTM-feed MRS model.
    cur.execute(
        """
        with active as (
          select id, version from models
          where type='mrs' and name=%s and status='ready'
          order by created_at desc limit 1
        )
        select r.slot_start, r.p_base, r.p_spike, r.p_drop
        from regime_states r join active a on a.version = r.model_version
        where r.area_id=%s and r.slot_start >= %s and r.slot_start < %s
        """,
        (f"mrs_{area_code}", area_id, start, end),
    )
    for ts, pb, ps, pd_ in cur.fetchall():
        cache.regime[ts] = (float(pb), float(ps), float(pd_))

    # Fuel prices — full history. Small table (~150-300 rows).
    cur.execute(
        """
        select ft.code, fp.ts, fp.price
        from fuel_prices fp join fuel_types ft on ft.id = fp.fuel_type_id
        order by ft.code, fp.ts
        """
    )
    for code, ts, price in cur.fetchall():
        cache.fuel_history.setdefault(code, []).append((ts, float(price)))

    # FX history — USDJPY only. Small table.
    cur.execute("select ts, rate from fx_rates where pair='USDJPY' order by ts")
    cache.fx_history = [(r[0], float(r[1])) for r in cur.fetchall()]

    # Holidays in the window. Small table.
    cur.execute(
        """
        select date, category from jp_holidays
        where date >= %s and date < %s
        """,
        (start.date(), end.date() + timedelta(days=1)),
    )
    for d, cat in cur.fetchall():
        cache.holidays.setdefault(d, set()).add(cat or "national")

    return cache


def _latest_le(history: list[tuple[datetime, float]], slot: datetime) -> float | None:
    """Return the latest history value with ts ≤ slot. None if no such value."""
    if not history:
        return None
    # Linear scan is fine — fuel_history has ~150 rows total.
    last: float | None = None
    for ts, val in history:
        if ts <= slot:
            last = val
        else:
            break
    return last


# ---------------------------------------------------------------------------
# Per-slot feature vector
# ---------------------------------------------------------------------------


def _slot_features(slot: datetime, cache: _AreaCache) -> list[float] | None:
    """Build the 27-dim feature vector for one slot. Returns None if missing
    the AR (price) or fundamental (stack) baseline — those slots are excluded
    from training and held-out evaluation."""
    price = cache.price_kwh.get(slot)
    stack = cache.stack_kwh.get(slot)
    if price is None or stack is None:
        return None

    # ch 0..1 — log price + log stack.
    f = [math.log(price), math.log(stack)]

    # ch 2..5 — calendar cyclical encodings.
    hour = slot.hour + slot.minute / 60.0
    f.append(math.sin(2 * math.pi * hour / 24.0))
    f.append(math.cos(2 * math.pi * hour / 24.0))
    f.append(math.sin(2 * math.pi * slot.weekday() / 7.0))
    f.append(math.cos(2 * math.pi * slot.weekday() / 7.0))

    # ch 6..10 — holiday + category one-hot.
    cats = cache.holidays.get(slot.date(), set())
    f.append(1.0 if cats else 0.0)
    for c in HOLIDAY_CATEGORIES:
        f.append(1.0 if c in cats else 0.0)

    # ch 11 — demand normalized.
    dem = cache.demand_mw.get(slot)
    f.append(dem / cache.demand_mean if dem is not None else 1.0)

    # ch 12..16 — genmix shares.
    gm = cache.genmix.get(slot, {})
    for k in ("vre", "nuclear", "lng", "coal", "hydro"):
        f.append(gm.get(k, 0.0))

    # ch 17..19 — weather (forward-fill nulls within the slot's exact ts only;
    # the LSTM can absorb scattered missing channels via 0-fill).
    w = cache.weather.get(slot, (None, None, None))
    f.append(w[0] if w[0] is not None else 0.0)
    f.append(w[1] if w[1] is not None else 0.0)
    f.append(w[2] if w[2] is not None else 0.0)

    # ch 20..23 — fuels (log scale) + USDJPY. Fuel codes match the live
    # `fuel_prices` table: lng_ccgt, lng_steam, coal, oil. We use lng_ccgt
    # as the LNG signal (CCGT is the marginal LNG plant in JEPX day-ahead).
    lng = _latest_le(cache.fuel_history.get("lng_ccgt", []), slot)
    coal_p = _latest_le(cache.fuel_history.get("coal", []), slot)
    oil_p = _latest_le(cache.fuel_history.get("oil", []), slot)
    fx = _latest_le(cache.fx_history, slot)
    f.append(math.log(lng) if lng and lng > 0 else 0.0)
    f.append(math.log(coal_p) if coal_p and coal_p > 0 else 0.0)
    f.append(math.log(oil_p) if oil_p and oil_p > 0 else 0.0)
    f.append(fx if fx is not None else 150.0)        # fallback to a neutral USDJPY.

    # ch 24..26 — regime probabilities (uniform prior fallback).
    pb, ps, pd_ = cache.regime.get(slot, (1 / 3, 1 / 3, 1 / 3))
    f.extend([pb, ps, pd_])

    assert len(f) == N_FEATURES_PER_SLOT, f"expected {N_FEATURES_PER_SLOT}, got {len(f)}"
    return f


# ---------------------------------------------------------------------------
# Window builders
# ---------------------------------------------------------------------------


def build_feature_window(
    cache: _AreaCache,
    origin: datetime,
    *,
    with_target: bool = True,
) -> FeatureWindow | None:
    """Build one (X, y, stack_horizon) example at the given origin.

    Returns None if any lookback or horizon slot is missing the AR (price)
    or fundamental (stack) baseline — the LSTM can't learn from a window
    with holes in the target series.

    `origin` is the END of the lookback window and the START of the
    horizon. lookback covers `[origin − LOOKBACK*30min, origin)`, horizon
    covers `[origin, origin + HORIZON*30min)`.
    """
    # Build the lookback feature matrix.
    X: list[list[float]] = []
    for i in range(LOOKBACK_SLOTS):
        slot = origin - timedelta(minutes=SLOT_MIN * (LOOKBACK_SLOTS - i))
        row = _slot_features(slot, cache)
        if row is None:
            return None
        X.append(row)

    # Stack output for the forecast horizon — used for raw-price reconstruction.
    stack_horizon: list[float] = []
    y: list[float] | None = [] if with_target else None
    for j in range(HORIZON_SLOTS):
        slot = origin + timedelta(minutes=SLOT_MIN * j)
        s = cache.stack_kwh.get(slot)
        if s is None:
            return None
        stack_horizon.append(s)
        if y is not None:
            p = cache.price_kwh.get(slot)
            if p is None:
                return None
            y.append(math.log(p))

    return FeatureWindow(
        area_code=cache.area_code,
        area_index=AREA_INDEX[cache.area_code],
        origin=origin,
        X=X,
        y=y,
        stack_horizon_kwh=stack_horizon,
    )


def build_training_examples(
    start: datetime,
    end: datetime,
    area_codes: tuple[AreaCode, ...] | None = None,
    *,
    stride: int = 4,
):
    """Yield FeatureWindow examples sliding through `[start, end)`.

    Stride controls the lookback step in slots; default 4 (= 2 hours)
    gives ~12 examples per area per day, ~12 × 365 × 9 = ~40K examples
    per training year. Tunable at training time.
    """
    if area_codes is None:
        area_codes = tuple(AREA_INDEX.keys())   # type: ignore[assignment]

    # Need extra lookback before `start` so the first origin's window has data.
    fetch_start = start - timedelta(minutes=SLOT_MIN * LOOKBACK_SLOTS)
    fetch_end = end + timedelta(minutes=SLOT_MIN * HORIZON_SLOTS)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select code, id::text from areas where code != 'SYS'")
        area_id_by_code = {r[0]: r[1] for r in cur.fetchall()}

        for code in area_codes:
            area_id = area_id_by_code[code]
            cache = build_area_cache(cur, area_id, code, fetch_start, fetch_end)
            origins = pd.date_range(
                start=start, end=end, freq=f"{SLOT_MIN}min", inclusive="left"
            )
            for i, origin in enumerate(origins):
                if i % stride != 0:
                    continue
                ts = origin.to_pydatetime().replace(tzinfo=UTC)
                window = build_feature_window(cache, ts, with_target=True)
                if window is not None:
                    yield window


def build_inference_window(
    area_code: AreaCode,
    origin: datetime | None = None,
) -> FeatureWindow:
    """One window at the given origin (defaults to current top-of-half-hour).

    Wraps the cache build + feature extraction for a single forecast call.
    Raises if the lookback or horizon has missing data — caller should
    handle by skipping that area's forecast for this run.
    """
    if origin is None:
        now = datetime.now(tz=UTC)
        # Round down to the nearest 30-minute boundary.
        floor_min = (now.minute // SLOT_MIN) * SLOT_MIN
        origin = now.replace(minute=floor_min, second=0, microsecond=0)

    fetch_start = origin - timedelta(minutes=SLOT_MIN * LOOKBACK_SLOTS)
    fetch_end = origin + timedelta(minutes=SLOT_MIN * HORIZON_SLOTS)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select id::text from areas where code = %s", (area_code,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"unknown area: {area_code}")
        area_id = cast(str, row[0])
        cache = build_area_cache(cur, area_id, area_code, fetch_start, fetch_end)

    window = build_feature_window(cache, origin, with_target=False)
    if window is None:
        raise RuntimeError(
            f"insufficient data for inference window at {origin.isoformat()} for {area_code}"
        )
    return window
