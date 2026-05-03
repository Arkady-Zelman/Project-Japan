"""Seed reference tables — areas, fuel_types, unit_types, jp_holidays.

Idempotent: re-running produces zero net changes (all UPSERTs use ON CONFLICT DO UPDATE
so cells like name_en stay in sync with the constants below).

Run from `apps/worker/`:
    ./.venv/bin/python -m seed.load_reference

Reads `SUPABASE_DB_URL` from `apps/worker/.env`. The connection string must point at the
Postgres role that owns these tables (service role for cloud, `postgres` user for the
local Supabase CLI stack).
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Literal

import psycopg
from dotenv import load_dotenv
from holidays import country_holidays

from .models import Area, FuelType, JpHoliday, UnitType

HolidayCategory = Literal["national", "obon", "newyear", "goldenweek"]

logger = logging.getLogger("seed.load_reference")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Constants — these don't change. New entries here need a matching CLAUDE.md /
# BUILD_SPEC update.
# ---------------------------------------------------------------------------

# 9 JEPX control areas + SYS (the system-wide reference series).
AREAS: tuple[Area, ...] = (
    Area(code="HK", name_en="Hokkaido", name_jp="北海道", tso="Hokkaido EPCO"),
    Area(code="TH", name_en="Tohoku", name_jp="東北", tso="Tohoku EPCO"),
    Area(code="TK", name_en="Tokyo", name_jp="東京", tso="TEPCO PG"),
    Area(code="CB", name_en="Chubu", name_jp="中部", tso="Chubu EPCO"),
    Area(code="HR", name_en="Hokuriku", name_jp="北陸", tso="Hokuriku EPCO"),
    Area(code="KS", name_en="Kansai", name_jp="関西", tso="Kansai EPCO"),
    Area(code="CG", name_en="Chugoku", name_jp="中国", tso="Chugoku EPCO"),
    Area(code="SK", name_en="Shikoku", name_jp="四国", tso="Shikoku EPCO"),
    Area(code="KY", name_en="Kyushu", name_jp="九州", tso="Kyushu EPCO"),
    Area(code="SYS", name_en="System (Japan-wide reference)", name_jp="全国", tso=None),
)

# Fuel categorisation — used in `generators.fuel_type_id` and `generation_mix_actuals`.
FUEL_TYPES: tuple[FuelType, ...] = (
    FuelType(code="lng_ccgt", name_en="LNG combined-cycle gas turbine"),
    FuelType(code="lng_steam", name_en="LNG steam turbine"),
    FuelType(code="coal", name_en="Coal"),
    FuelType(code="oil", name_en="Oil"),
    FuelType(code="nuclear", name_en="Nuclear"),
    FuelType(code="solar", name_en="Solar PV"),
    FuelType(code="wind", name_en="Wind"),
    FuelType(code="hydro", name_en="Hydro (run-of-river + reservoir)"),
    FuelType(code="geothermal", name_en="Geothermal"),
    FuelType(code="biomass", name_en="Biomass"),
    FuelType(code="pumped_storage", name_en="Pumped-storage hydro"),
    FuelType(code="battery", name_en="Battery storage"),
)

# Unit-type taxonomy — distinguishes thermodynamic cycle / dispatch shape.
UNIT_TYPES: tuple[UnitType, ...] = (
    UnitType(code="ccgt", name_en="Combined-cycle gas turbine"),
    UnitType(code="steam", name_en="Steam turbine"),
    UnitType(code="ocgt", name_en="Open-cycle gas turbine / peaker"),
    UnitType(code="ic_diesel", name_en="Internal-combustion / diesel"),
    UnitType(code="hydro_run", name_en="Run-of-river hydro"),
    UnitType(code="hydro_dam", name_en="Reservoir / dam hydro"),
    UnitType(code="pumped_storage", name_en="Pumped-storage hydro"),
    UnitType(code="vre", name_en="Variable renewable (solar/wind, non-dispatchable)"),
)

# Holiday horizon: 5 years history + 3 years forward for backtest + dispatch lookahead.
HOLIDAY_YEAR_START = 2020
HOLIDAY_YEAR_END = 2027


# ---------------------------------------------------------------------------
# Holiday categorisation — Japan's `holidays` package returns national stat
# holidays. We additionally label Obon, New Year, and Golden Week windows
# because power demand patterns track those windows even when individual days
# are not statutory holidays.
# ---------------------------------------------------------------------------


def categorise_holiday(d: date, name_en: str) -> HolidayCategory:
    """Bucket a Japanese calendar date into one of: national | obon | newyear | goldenweek."""
    if d.month == 12 and d.day >= 30:
        return "newyear"
    if d.month == 1 and d.day <= 3:
        return "newyear"
    if d.month == 4 and d.day >= 29:
        return "goldenweek"
    if d.month == 5 and d.day <= 5:
        return "goldenweek"
    if d.month == 8 and 13 <= d.day <= 16:
        return "obon"
    return "national"


def build_holidays(year_start: int, year_end: int) -> list[JpHoliday]:
    """Pull statutory holidays from the `holidays` package and add the three
    cultural windows (newyear, goldenweek, obon) that aren't always statutory.
    """
    out: dict[date, JpHoliday] = {}

    # Statutory holidays from the `holidays` package.
    jp = country_holidays("JP", years=range(year_start, year_end + 1))
    for d, name_en in jp.items():
        out[d] = JpHoliday(
            date=d,
            name_en=name_en,
            name_jp=None,  # `holidays` ships English JP names; JP-locale comes later
            category=categorise_holiday(d, name_en),
        )

    # Add the cultural windows that aren't always public holidays.
    for year in range(year_start, year_end + 1):
        # New Year window (Dec 30–31, Jan 2–3): Jan 1 is statutory; the others are not.
        for month, day in [(12, 30), (12, 31), (1, 2), (1, 3)]:
            d = date(year if month == 12 else year, month, day)
            out.setdefault(d, JpHoliday(date=d, name_en="New Year window", category="newyear"))
        # Golden Week (Apr 30, May 2): bridge days between statutory holidays.
        for month, day in [(4, 30), (5, 2)]:
            d = date(year, month, day)
            out.setdefault(
                d, JpHoliday(date=d, name_en="Golden Week bridge", category="goldenweek")
            )
        # Obon window (Aug 13–16): not statutory but most workplaces close.
        for day in range(13, 17):
            d = date(year, 8, day)
            out.setdefault(d, JpHoliday(date=d, name_en="Obon", category="obon"))

    return sorted(out.values(), key=lambda h: h.date)


# ---------------------------------------------------------------------------
# UPSERT helpers
# ---------------------------------------------------------------------------


def upsert_areas(cur: psycopg.Cursor, rows: tuple[Area, ...]) -> int:
    cur.executemany(
        """
        insert into areas (code, name_en, name_jp, tso, timezone)
        values (%s, %s, %s, %s, %s)
        on conflict (code) do update set
          name_en = excluded.name_en,
          name_jp = excluded.name_jp,
          tso = excluded.tso,
          timezone = excluded.timezone
        """,
        [(a.code, a.name_en, a.name_jp, a.tso, a.timezone) for a in rows],
    )
    return cur.rowcount


def upsert_fuel_types(cur: psycopg.Cursor, rows: tuple[FuelType, ...]) -> int:
    cur.executemany(
        """
        insert into fuel_types (code, name_en) values (%s, %s)
        on conflict (code) do update set name_en = excluded.name_en
        """,
        [(f.code, f.name_en) for f in rows],
    )
    return cur.rowcount


def upsert_unit_types(cur: psycopg.Cursor, rows: tuple[UnitType, ...]) -> int:
    cur.executemany(
        """
        insert into unit_types (code, name_en) values (%s, %s)
        on conflict (code) do update set name_en = excluded.name_en
        """,
        [(u.code, u.name_en) for u in rows],
    )
    return cur.rowcount


def upsert_holidays(cur: psycopg.Cursor, rows: list[JpHoliday]) -> int:
    cur.executemany(
        """
        insert into jp_holidays (date, name_jp, name_en, category)
        values (%s, %s, %s, %s)
        on conflict (date) do update set
          name_jp = excluded.name_jp,
          name_en = excluded.name_en,
          category = excluded.category
        """,
        [(h.date, h.name_jp, h.name_en, h.category) for h in rows],
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    # `apps/worker/.env` is the canonical env file for the worker. Operator-managed.
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path)

    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.error(
            "SUPABASE_DB_URL not set in %s — needed to apply seed data. Aborting.", env_path
        )
        return 1

    holidays_rows = build_holidays(HOLIDAY_YEAR_START, HOLIDAY_YEAR_END)
    logger.info(
        "Prepared seed: %d areas, %d fuels, %d unit types, %d holiday rows (years %d-%d).",
        len(AREAS),
        len(FUEL_TYPES),
        len(UNIT_TYPES),
        len(holidays_rows),
        HOLIDAY_YEAR_START,
        HOLIDAY_YEAR_END,
    )

    # prepare_threshold=None disables prepared statements — required when
    # connecting through Supabase's transaction pooler (port 6543), which
    # doesn't support PREPARE.
    with psycopg.connect(db_url, autocommit=False, prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            n_a = upsert_areas(cur, AREAS)
            n_f = upsert_fuel_types(cur, FUEL_TYPES)
            n_u = upsert_unit_types(cur, UNIT_TYPES)
            n_h = upsert_holidays(cur, holidays_rows)
        conn.commit()

    logger.info(
        "Seed complete: areas=%d fuels=%d unit_types=%d holidays=%d (rowcount = inserted+updated).",
        n_a,
        n_f,
        n_u,
        n_h,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
