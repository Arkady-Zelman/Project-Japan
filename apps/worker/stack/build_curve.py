"""Merit-order stack-clearing engine — batched implementation.

Per BUILD_SPEC §7.3:

  1. For each (area, slot) in the window, pull all `generators` for the area.
  2. Compute SRMC per generator using `stack/srmc.py`.
  3. Reduce variable-renewable capacity to the slot's actual solar/wind
     output — from `generation_mix_actuals` if present, else from
     `stack/weather_proxy.py`.
  4. Sort by SRMC ascending. Build cumulative-MW curve.
  5. Find the marginal unit (first cumulative ≥ demand). Modelled price
     = its SRMC.
  6. Persist `stack_curves` (curve_jsonb + inputs_hash) and
     `stack_clearing_prices`.

Performance: one bulk fetch per (area, input table) instead of per-slot
roundtrips. ~10K slots/area in seconds, not minutes.

CLI:
    python -m stack.build_curve --area TK --slot 2024-04-15T05:00Z
    python -m stack.build_curve --start 2023-01-01 --end 2024-04-01 \\
        [--areas TK,KS]
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import psycopg

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock

from . import srmc, weather_proxy

logger = logging.getLogger("stack.build_curve")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# Default availability factors by fuel type — until generator_availability is populated.
_DEFAULT_AVAILABILITY: dict[str, float] = {
    "lng_ccgt": 0.90,
    "lng_steam": 0.85,
    "coal": 0.85,
    "oil": 0.40,
    "nuclear": 0.30,    # Reflects 2023-2026 Japan fleet status.
    "pumped_storage": 1.00,
    "biomass": 0.70,
    "hydro": 0.30,
    "geothermal": 0.85,
    "solar": 0.0,
    "wind": 0.0,
    "battery": 0.50,
}


def _availability_factor(fuel_code: str) -> float:
    return _DEFAULT_AVAILABILITY.get(fuel_code, 0.85)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class _GeneratorRow:
    id: str
    name: str
    fuel_code: str
    capacity_mw: float
    efficiency: float | None
    variable_om_jpy_mwh: float | None
    co2_intensity_t_mwh: float | None
    availability_factor: float | None  # Per-unit override; falls back to fleet default.


@dataclass
class _AreaCache:
    """All inputs cached for one area + window. Per-slot lookups happen in memory."""

    area_id: str
    area_code: str
    generators: list[_GeneratorRow]
    # Fuel prices per fuel_code: sorted list of (ts, price, unit). Lookup latest ≤ slot.
    fuel_history: dict[str, list[tuple[datetime, float, str]]]
    # USDJPY: sorted list of (ts, rate). Lookup latest ≤ slot.
    fx_history: list[tuple[datetime, float]]
    # Weather: dict[ts → (ghi, wind_mps)]
    weather_by_ts: dict[datetime, tuple[float | None, float | None]]
    # Solar/wind actuals: dict[ts → {fuel_code: output_mw}]
    vre_actuals_by_ts: dict[datetime, dict[str, float | None]]
    # Demand: dict[ts → demand_mw]
    demand_by_ts: dict[datetime, float | None]
    # Per-generator availability (MW available at slot). When present, beats
    # per-unit metadata.availability_factor and fleet-wide defaults.
    availability_by_gen_ts: dict[tuple[str, datetime], float]


# ---------------------------------------------------------------------------
# DB bulk loaders
# ---------------------------------------------------------------------------


def _load_generators(cur: psycopg.Cursor, area_id: str) -> list[_GeneratorRow]:
    cur.execute(
        """
        select g.id::text, g.name, ft.code, g.capacity_mw, g.efficiency,
               g.variable_om_jpy_mwh, g.co2_intensity_t_mwh,
               (g.metadata->>'availability_factor')::numeric
        from generators g
        join fuel_types ft on ft.id = g.fuel_type_id
        where g.area_id = %s
          and (g.retired is null or g.retired > current_date)
        """,
        (area_id,),
    )
    return [
        _GeneratorRow(
            id=r[0], name=r[1], fuel_code=r[2], capacity_mw=float(r[3]),
            efficiency=float(r[4]) if r[4] is not None else None,
            variable_om_jpy_mwh=float(r[5]) if r[5] is not None else None,
            co2_intensity_t_mwh=float(r[6]) if r[6] is not None else None,
            availability_factor=float(r[7]) if r[7] is not None else None,
        )
        for r in cur.fetchall()
    ]


def _load_area_cache(
    cur: psycopg.Cursor, area_id: str, area_code: str, start: datetime, end: datetime
) -> _AreaCache:
    """Single bulk fetch for everything we need for one area + window."""
    generators = _load_generators(cur, area_id)

    # Fuel prices — full history (small table; ~150 rows). Sorted ascending by ts.
    cur.execute(
        """
        select ft.code, fp.ts, fp.price, fp.unit
        from fuel_prices fp join fuel_types ft on ft.id = fp.fuel_type_id
        order by ft.code, fp.ts
        """
    )
    fuel_history: dict[str, list[tuple[datetime, float, str]]] = {}
    for code, ts, price, unit in cur.fetchall():
        fuel_history.setdefault(code, []).append((ts, float(price), unit))

    # FX history — full, sorted ascending by ts. Small table.
    cur.execute("select ts, rate from fx_rates where pair='USDJPY' order by ts")
    fx_history = [(r[0], float(r[1])) for r in cur.fetchall()]

    # Weather — only rows in window for this area.
    cur.execute(
        """
        select ts, ghi_w_m2, wind_mps from weather_obs
        where area_id=%s and ts >= %s and ts < %s and forecast_horizon_h=0
        """,
        (area_id, start, end),
    )
    weather_by_ts: dict[datetime, tuple[float | None, float | None]] = {}
    for ts, ghi, wind in cur.fetchall():
        weather_by_ts[ts] = (
            float(ghi) if ghi is not None else None,
            float(wind) if wind is not None else None,
        )

    # Solar/wind actuals from generation_mix_actuals.
    cur.execute(
        """
        select m.slot_start, ft.code, m.output_mw
        from generation_mix_actuals m join fuel_types ft on ft.id=m.fuel_type_id
        where m.area_id=%s and m.slot_start >= %s and m.slot_start < %s
          and ft.code in ('solar','wind')
        """,
        (area_id, start, end),
    )
    vre_actuals: dict[datetime, dict[str, float | None]] = {}
    for ts, code, mw in cur.fetchall():
        vre_actuals.setdefault(ts, {})[code] = float(mw) if mw is not None else None

    # Per-generator availability (M10C L9). Optional table; falls back to
    # per-unit metadata.availability_factor or fleet-wide _DEFAULT_AVAILABILITY.
    cur.execute(
        """
        select generator_id::text, slot_start, available_mw
        from generator_availability
        where slot_start >= %s and slot_start < %s
        """,
        (start, end),
    )
    availability_by_gen_ts: dict[tuple[str, datetime], float] = {}
    for gid, ts, mw in cur.fetchall():
        if mw is None:
            continue
        availability_by_gen_ts[(gid, ts)] = float(mw)

    # Demand actuals.
    cur.execute(
        """
        select slot_start, demand_mw from demand_actuals
        where area_id=%s and slot_start >= %s and slot_start < %s
        """,
        (area_id, start, end),
    )
    demand_by_ts: dict[datetime, float | None] = {
        ts: (float(mw) if mw is not None else None) for ts, mw in cur.fetchall()
    }

    return _AreaCache(
        area_id=area_id,
        area_code=area_code,
        generators=generators,
        fuel_history=fuel_history,
        fx_history=fx_history,
        weather_by_ts=weather_by_ts,
        vre_actuals_by_ts=vre_actuals,
        demand_by_ts=demand_by_ts,
        availability_by_gen_ts=availability_by_gen_ts,
    )


# ---------------------------------------------------------------------------
# Per-slot lookups (in-memory, no DB)
# ---------------------------------------------------------------------------


def _latest_le(history: list, slot: datetime):
    """Latest tuple in `history` (sorted asc by ts) with ts ≤ slot.

    Accepts any tuple shape whose first element is a datetime. Returns the
    full tuple unchanged so the caller can read whatever fields it needs.
    """
    if not history:
        return None
    keys = [h[0] for h in history]
    idx = bisect.bisect_right(keys, slot) - 1
    if idx < 0:
        return None
    return history[idx]


def _slot_inputs(
    cache: _AreaCache, slot: datetime
) -> tuple[float | None, float, str, dict[str, float]]:
    """Return (demand_mw, vre_mw, vre_source, fuel_jpy_mwh_thermal_by_code)."""
    # Demand — exact, then hour-rounded fallback for hourly sources.
    demand = cache.demand_by_ts.get(slot)
    if demand is None:
        rounded = slot.replace(minute=0, second=0, microsecond=0)
        if rounded != slot:
            demand = cache.demand_by_ts.get(rounded)

    # VRE — actuals if present, else weather proxy.
    actuals = cache.vre_actuals_by_ts.get(slot, {})
    weather = cache.weather_by_ts.get(slot)
    if weather is None:
        # Try hour-rounded weather (weather_obs is hourly).
        rounded = slot.replace(minute=0, second=0, microsecond=0)
        weather = cache.weather_by_ts.get(rounded)
    ghi = weather[0] if weather else None
    wind_mps = weather[1] if weather else None

    sources: list[str] = []
    if "solar" in actuals and actuals["solar"] is not None:
        solar_mw = actuals["solar"]
        sources.append("actuals")
    else:
        solar_mw = weather_proxy.solar_proxy_mw(cache.area_code, ghi)
        sources.append("proxy")
    if "wind" in actuals and actuals["wind"] is not None:
        wind_mw = actuals["wind"]
        sources.append("actuals")
    else:
        wind_mw = weather_proxy.wind_proxy_mw(cache.area_code, wind_mps)
        sources.append("proxy")
    vre_src = (
        "actuals" if all(s == "actuals" for s in sources) else
        "weather_proxy" if all(s == "proxy" for s in sources) else "mixed"
    )

    # FX
    fx_row = _latest_le(cache.fx_history, slot)
    fx = fx_row[1] if fx_row else None

    # Fuel prices → ¥/MWh thermal.
    fuel_jpy: dict[str, float] = {}
    if fx is not None:
        for fuel_code, history in cache.fuel_history.items():
            row = _latest_le(history, slot)
            if not row:
                continue
            _, price, unit = row
            try:
                fuel_jpy[fuel_code] = srmc.fuel_price_jpy_mwh_thermal(
                    fuel_code=fuel_code, price=price, unit=unit, fx_usdjpy=fx,
                )
            except ValueError:
                continue

    return demand, solar_mw + wind_mw, vre_src, fuel_jpy


# ---------------------------------------------------------------------------
# Curve builder — pure function, no I/O
# ---------------------------------------------------------------------------


def _build_payload(
    cache: _AreaCache,
    slot: datetime,
    demand: float | None,
    vre_mw: float,
    vre_src: str,
    fuel_jpy: dict[str, float],
) -> tuple[list[dict], float | None, str | None, str]:
    """Return (curve_steps, modelled_price_jpy_mwh, marginal_unit_id, inputs_hash)."""
    units: list[tuple[_GeneratorRow, float, float]] = []
    from .models import Generator as _GenModel

    for g in cache.generators:
        thermal = fuel_jpy.get(g.fuel_code)
        if thermal is None and g.fuel_code in {"lng_ccgt", "lng_steam"}:
            thermal = fuel_jpy.get("lng_ccgt") or fuel_jpy.get("lng_steam")
        gen_proxy = _GenModel(
            name=g.name,
            area_code=cache.area_code,
            fuel_type_code=g.fuel_code,
            capacity_mw=g.capacity_mw,
            efficiency=g.efficiency,
            variable_om_jpy_mwh=g.variable_om_jpy_mwh,
            co2_intensity_t_mwh=g.co2_intensity_t_mwh,
        )
        s = srmc.srmc_jpy_mwh(gen_proxy, fuel_price_jpy_mwh_thermal=thermal)
        # Time-varying availability (M10C L9) beats per-unit override beats
        # fleet default. SESSION_LOG_2026-05-07 explains the rationale for the
        # legacy per-area nuclear overrides.
        explicit_mw = cache.availability_by_gen_ts.get((g.id, slot))
        if explicit_mw is not None:
            eff_mw = explicit_mw
        else:
            avail = g.availability_factor if g.availability_factor is not None else _availability_factor(g.fuel_code)
            eff_mw = g.capacity_mw * avail
        units.append((g, s, eff_mw))

    units.sort(key=lambda x: x[1])

    cumulative = 0.0
    steps: list[dict] = []
    if vre_mw > 0:
        cumulative += vre_mw
        steps.append({
            "mw_cumulative": round(cumulative, 2),
            "srmc_jpy_mwh": 0.0,
            "generator_id": None,
            "fuel_code": "vre",
            "name": f"VRE ({vre_src})",
        })
    for g, s, eff_mw in units:
        cumulative += eff_mw
        steps.append({
            "mw_cumulative": round(cumulative, 2),
            "srmc_jpy_mwh": round(s, 4),
            "generator_id": g.id,
            "fuel_code": g.fuel_code,
            "name": g.name,
        })

    marginal_id: str | None = None
    modelled_price: float | None = None
    if demand is not None and demand > 0:
        for step in steps:
            if step["mw_cumulative"] >= demand:
                marginal_id = step["generator_id"]
                modelled_price = step["srmc_jpy_mwh"]
                break

    h = hashlib.blake2b(digest_size=16)
    h.update(json.dumps({
        "fuels": sorted(fuel_jpy.items()),
        "demand": demand,
        "vre": round(vre_mw, 2),
        # Hash on (id, effective_mw) — availability changes alter eff_mw
        # without touching nameplate capacity, so we must include eff_mw.
        "gen_set": sorted((g.id, round(eff_mw, 2)) for g, _, eff_mw in units),
    }, sort_keys=True, default=str).encode())
    return steps, modelled_price, marginal_id, h.hexdigest()


# ---------------------------------------------------------------------------
# Persistence — batched UPSERT
# ---------------------------------------------------------------------------


def _upsert_batch(
    cur: psycopg.Cursor,
    area_id: str,
    rows: list[tuple[datetime, list[dict], float | None, float | None, str | None, str]],
) -> tuple[int, int]:
    """Return (new_or_updated_writes, cache_hits).

    Two `executemany` calls — one per target table. Each round-trips once
    to the pooler regardless of batch size, so 500 slots → 2 round-trips.
    """
    if not rows:
        return 0, 0

    # 1) Pre-fetch existing hashes for cache-skip.
    slots = [r[0] for r in rows]
    cur.execute(
        "select slot_start, inputs_hash from stack_curves "
        "where area_id=%s and slot_start = any(%s)",
        (area_id, slots),
    )
    existing_hashes: dict[datetime, str] = dict(cur.fetchall())

    curves_payload: list[tuple] = []
    clearing_payload: list[tuple] = []
    cache_hits = 0
    for slot, steps, model_price, demand, marginal_id, inputs_hash in rows:
        if existing_hashes.get(slot) == inputs_hash:
            cache_hits += 1
            continue
        curves_payload.append(
            (area_id, slot, json.dumps(steps), inputs_hash)
        )
        clearing_payload.append(
            (area_id, slot, model_price, demand, marginal_id)
        )

    if curves_payload:
        # UPSERT stack_curves keyed on (area_id, slot_start) — schema has
        # `unique (area_id, slot_start)` so this conflict target is valid.
        cur.executemany(
            """
            insert into stack_curves (area_id, slot_start, curve_jsonb, inputs_hash)
            values (%s, %s, %s, %s)
            on conflict (area_id, slot_start) do update set
              curve_jsonb = excluded.curve_jsonb,
              inputs_hash = excluded.inputs_hash
            """,
            curves_payload,
        )
        # UPSERT stack_clearing_prices. Don't link to stack_curves.id — the
        # FK is nullable, and (area_id, slot_start) is the natural join key.
        cur.executemany(
            """
            insert into stack_clearing_prices
              (area_id, slot_start, modelled_price_jpy_mwh,
               modelled_demand_mw, marginal_unit_id)
            values (%s, %s, %s, %s, %s)
            on conflict (area_id, slot_start) do update set
              modelled_price_jpy_mwh = excluded.modelled_price_jpy_mwh,
              modelled_demand_mw = excluded.modelled_demand_mw,
              marginal_unit_id = excluded.marginal_unit_id
            """,
            clearing_payload,
        )

    return len(curves_payload), cache_hits


# ---------------------------------------------------------------------------
# Build window
# ---------------------------------------------------------------------------


def build_window(
    start: date,
    end: date,
    areas: list[str] | None = None,
) -> dict:
    """Build curves for every (area, slot) in [start, end). Batched I/O."""
    summary: dict = {"areas": {}, "slots_processed": 0, "writes": 0, "skipped_cache": 0}

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("select id::text, code from areas where code != 'SYS'")
            areas_all = list(cur.fetchall())

    target = [(aid, code) for aid, code in areas_all if not areas or code in areas]
    start_dt = datetime.combine(start, datetime.min.time(), UTC)
    end_dt = datetime.combine(end, datetime.min.time(), UTC)

    for area_id, area_code in target:
        with compute_run("stack_build") as run:
            run.set_input({
                "area": area_code,
                "start": start.isoformat(),
                "end": end.isoformat(),
            })
            with connect() as conn:
                with conn.cursor() as cur:
                    advisory_lock(cur, f"stack_build_{area_code}")
                    cache = _load_area_cache(cur, area_id, area_code, start_dt, end_dt)
                    if not cache.generators:
                        run.set_output({"skipped": "no generators"})
                        continue

                    slots = sorted(cache.demand_by_ts.keys())
                    rows: list[tuple] = []
                    for slot in slots:
                        demand, vre_mw, vre_src, fuel_jpy = _slot_inputs(cache, slot)
                        steps, model_price, marginal_id, inputs_hash = _build_payload(
                            cache, slot, demand, vre_mw, vre_src, fuel_jpy
                        )
                        rows.append((slot, steps, model_price, demand, marginal_id, inputs_hash))

                    # Chunked UPSERT to keep transactions reasonable.
                    area_writes = 0
                    area_cache = 0
                    for i in range(0, len(rows), 500):
                        chunk = rows[i:i + 500]
                        w, c = _upsert_batch(cur, area_id, chunk)
                        area_writes += w
                        area_cache += c
                conn.commit()

            summary["areas"][area_code] = {
                "slots": len(slots), "writes": area_writes, "cache_hits": area_cache,
            }
            summary["slots_processed"] += len(slots)
            summary["writes"] += area_writes
            summary["skipped_cache"] += area_cache
            run.set_output(summary["areas"][area_code])
            logger.info(
                "%s: slots=%d writes=%d cache=%d",
                area_code, len(slots), area_writes, area_cache,
            )

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_iso_dt(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stack.build_curve")
    parser.add_argument("--area", help="Single-slot mode: area code")
    parser.add_argument("--slot", help="Single-slot mode: ISO 8601 slot_start")
    parser.add_argument("--start", type=date.fromisoformat, help="Window mode")
    parser.add_argument("--end", type=date.fromisoformat, help="Window mode")
    parser.add_argument("--areas", help="Comma-separated codes (window mode)")
    args = parser.parse_args(argv)

    if args.area and args.slot:
        slot = _parse_iso_dt(args.slot)
        end = (slot + timedelta(minutes=1)).date() + timedelta(days=1)
        summary = build_window(slot.date(), end, [args.area])
        logger.info("single-slot summary: %s", summary)
        return 0

    if args.start and args.end:
        areas = (
            [a.strip() for a in args.areas.split(",")] if args.areas else None
        )
        summary = build_window(args.start, args.end, areas)
        logger.info("window summary: %s", summary)
        return 0

    parser.error("Provide either (--area + --slot) or (--start + --end).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
