"""Hourly generation mix by fuel type — per-utility area-supply CSV scraper.

Source: each Japanese utility publishes an "エリア需給実績" (area supply-demand
record) CSV per fiscal year (Apr–Mar) at a stable URL. The CSV reports hourly
output by fuel category in `万kWh` (10,000 kWh per hour = 10 MW continuous):

  DATE, TIME, <area>需要 (demand),
  原子力 (Nuclear), 火力 (Thermal — combined LNG+coal+oil+biomass-mix),
  水力 (Hydro), 地熱 (Geothermal), バイオマス (Biomass dedicated),
  太陽光発電実績 (Solar actual), 太陽光出力制御量 (Solar curtailment),
  風力発電実績 (Wind actual), 風力出力制御量 (Wind curtailment),
  揚水 (Pumped storage), 連系線 (Interconnection), 合計 (Total)

This is the official TSO publication used by OCCTO for cross-area aggregation,
and replaces the spec's "japanesepower.org HH Data" plan (which doesn't expose
generation mix). See BUILD_SPEC §7.1.

M3 implements TEPCO (`area_id='TK'`) only as proof of architecture. The other
8 utility URLs are documented in `_AREA_SOURCES` below and follow the same
parser; rolling them out is a mechanical follow-up.

Fuel-category mapping into `generation_mix_actuals.fuel_type_id`:

  CSV column          → fuel_types.code     Notes
  ----------------------------------------------------------
  原子力               → nuclear
  火力                 → lng_ccgt            (best single-bucket proxy; spec
                                              recognises this is a coarse
                                              consolidation. v3 ingest can
                                              split via separate utility data
                                              when METI publishes per-fuel
                                              breakouts.)
  水力                 → hydro
  地熱                 → geothermal
  バイオマス            → biomass
  太陽光発電実績        → solar
  風力発電実績          → wind
  揚水 (positive only) → pumped_storage     (pump-up shows as negative;
                                              we record only generation
                                              direction and treat
                                              negatives as 0)
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock
from common.retry import retry_transient

from .models import IngestResult


class _UtilitySource(BaseModel):
    """Per-utility area-supply CSV publication.

    Two URL patterns may be set:

    - `annual_url_pattern` ({fy}): fiscal-year file, hourly granule, coarse
      thermal (one `火力` column). Covers historical data.
    - `monthly_url_pattern` ({yyyy}{mm}): per-calendar-month file, 30-min
      granule, fine thermal split (LNG/coal/oil/other/biomass-mix), already
      in MW. Covers recent / current data.

    The parser tries monthly first (richer + fresher), falls back to annual
    for older months. UPSERT handles any duplicates.
    """

    model_config = ConfigDict(extra="forbid")

    area_code: str
    name: str
    annual_url_pattern: str | None = None
    monthly_url_pattern: str | None = None
    encoding: str = "cp932"
    implemented: bool = False


_AREA_SOURCES: dict[str, _UtilitySource] = {
    "TK": _UtilitySource(
        area_code="TK",
        name="TEPCO PG",
        annual_url_pattern="https://www.tepco.co.jp/forecast/html/images/area-{fy}.csv",
        monthly_url_pattern=(
            "https://www.tepco.co.jp/forecast/html/images/eria_jukyu_{yyyy}{mm:02d}_03.csv"
        ),
        encoding="utf-8-sig",
        implemented=True,
    ),
    # Below: documented for v2 expansion. URLs may need confirmation; the
    # parser below is generic across utilities so rolling each one out is
    # changing `implemented=True` and adjusting any column-name idiosyncrasies.
    "HK": _UtilitySource(
        area_code="HK", name="Hokkaido EPCO",
        annual_url_pattern="http://denkiyoho.hepco.co.jp/area/data/jukyu_{fy}_hokkaido.csv",
    ),
    "TH": _UtilitySource(
        area_code="TH", name="Tohoku EPCO",
        annual_url_pattern="https://setsuden.nw.tohoku-epco.co.jp/common/demand/juyo_{fy}_tohoku.csv",
    ),
    "CB": _UtilitySource(
        area_code="CB", name="Chubu EPCO",
        annual_url_pattern="https://powergrid.chuden.co.jp/denkiyoho/csv/area_jukyu_{fy}.csv",
    ),
    "HR": _UtilitySource(
        area_code="HR", name="Hokuriku EPCO",
        annual_url_pattern="https://www.rikuden.co.jp/nw_jyukyudata/attach/area_jukyu_{fy}.csv",
    ),
    "KS": _UtilitySource(
        area_code="KS", name="Kansai EPCO",
        annual_url_pattern="https://www.kansai-td.co.jp/yamasou/area_jukyu_{fy}.csv",
    ),
    "CG": _UtilitySource(
        area_code="CG", name="Chugoku EPCO",
        annual_url_pattern="https://www.energia.co.jp/nw/jukyuu/sys/area_jukyu_{fy}.csv",
    ),
    "SK": _UtilitySource(
        area_code="SK", name="Shikoku EPCO",
        annual_url_pattern="https://www.yonden.co.jp/nw/area_jukyu/csv/jukyu_{fy}.csv",
    ),
    "KY": _UtilitySource(
        area_code="KY", name="Kyushu EPCO",
        annual_url_pattern="https://www.kyuden.co.jp/td_area_jukyu/csv/jukyu_{fy}.csv",
    ),
}


# Maps the CSV's Japanese fuel-bucket header → the `fuel_types.code` we store
# against. Two header dialects:
#
#   ANNUAL (area-{fy}.csv): `火力` is a single combined-thermal column. We
#   map it to `lng_ccgt` as the best single-bucket proxy; coarse but useful.
#
#   MONTHLY (eria_jukyu_YYYYMM_03.csv): thermal split into LNG / coal / oil /
#   `その他` (other-mixed-thermal). Plus dedicated battery / 蓄電池. Richer.
#
# Unmapped columns (出力制御量 = curtailment, 連系線 = interconnect,
# 合計 = total, 需要 = demand, その他 in mix = unclassified) are skipped —
# they belong elsewhere or are derived.
_FUEL_HEADER_TO_CODE_ANNUAL: dict[str, str] = {
    "原子力": "nuclear",
    "火力": "lng_ccgt",     # Coarse: combined thermal. See module docstring.
    "水力": "hydro",
    "地熱": "geothermal",
    "バイオマス": "biomass",
    "太陽光発電実績": "solar",
    "風力発電実績": "wind",
    "揚水": "pumped_storage",
}

_FUEL_HEADER_TO_CODE_MONTHLY: dict[str, str] = {
    "原子力": "nuclear",
    "火力(LNG)": "lng_ccgt",
    "火力(石炭)": "coal",
    "火力(石油)": "oil",
    # 火力(その他) covers biomass-mixed-fuel + other unclassified thermal;
    # we drop it rather than misattribute (would double-count with バイオマス).
    "水力": "hydro",
    "地熱": "geothermal",
    "バイオマス": "biomass",
    "太陽光発電実績": "solar",
    "風力発電実績": "wind",
    "揚水": "pumped_storage",
    "蓄電池": "battery",
}

# Curtailment columns map onto the same fuel as the actual-output column —
# we record positive curtailment via `generation_mix_actuals.curtailment_mw`.
_CURTAIL_HEADER_TO_CODE: dict[str, str] = {
    "太陽光出力制御量": "solar",
    "風力出力制御量": "wind",
}


class _MixRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_code: str
    slot_start: datetime
    fuel_code: str
    output_mw: float | None
    curtailment_mw: float | None
    source: str = "tso_area_jukyu"


class _FormatSpec(BaseModel):
    """How to read one CSV publication style (annual vs monthly)."""

    model_config = ConfigDict(extra="forbid")

    name: str                   # 'annual' or 'monthly' — used in error messages
    skiprows: int               # Header rows to drop before reading
    columns: list[str]          # Column names assigned positionally
    fuel_map: dict[str, str]    # CSV header → fuel_types.code
    mw_multiplier: float        # Cell value × this = MW. 10.0 for 万kWh/hr, 1.0 for MW.


# Annual file: 3 noise rows (unit + 2-row broken header), then hourly data
# in 万kWh-per-hour. Layout verified on TEPCO area-2023.csv.
_ANNUAL_FMT = _FormatSpec(
    name="annual",
    skiprows=3,
    columns=[
        "DATE", "TIME", "demand",
        "原子力", "火力", "水力", "地熱", "バイオマス",
        "太陽光発電実績", "太陽光出力制御量",
        "風力発電実績", "風力出力制御量",
        "揚水", "連系線", "合計",
    ],
    fuel_map=_FUEL_HEADER_TO_CODE_ANNUAL,
    mw_multiplier=10.0,
)

# Monthly file: 1 noise row (`単位[MW平均],,,供給力`) + 1 actual single-row
# header. 30-min granule. Values already in MW (multiplier 1.0). Thermal
# split into LNG/coal/oil/other; battery is its own column.
_MONTHLY_FMT = _FormatSpec(
    name="monthly",
    skiprows=2,
    columns=[
        "DATE", "TIME", "demand",
        "原子力", "火力(LNG)", "火力(石炭)", "火力(石油)", "火力(その他)",
        "水力", "地熱", "バイオマス",
        "太陽光発電実績", "太陽光出力制御量",
        "風力発電実績", "風力出力制御量",
        "揚水", "蓄電池", "連系線", "その他", "合計",
    ],
    fuel_map=_FUEL_HEADER_TO_CODE_MONTHLY,
    mw_multiplier=1.0,
)


@retry_transient
def _fetch_csv(url: str, encoding: str, fmt: _FormatSpec) -> pd.DataFrame:
    """Download a CSV and return a DataFrame with positional columns assigned.

    Both publication styles have header rows that don't fit pandas's
    multi-header parser cleanly (row 1 has fewer cells than the data rows
    because spanning header cells aren't padded). Fix: skip all noise rows,
    read with header=None, assign column names from `fmt.columns`.

    Raises ValueError if column count mismatches — the operator should
    investigate (TSO changed the format) rather than silently ingest garbage.
    """
    r = httpx.get(url, timeout=120, headers={"User-Agent": "jepx-storage-ingest/1.0"})
    r.raise_for_status()
    text = r.content.decode(encoding, errors="replace")
    df = pd.read_csv(io.StringIO(text), skiprows=fmt.skiprows, header=None)
    if df.shape[1] != len(fmt.columns):
        raise ValueError(
            f"Unexpected column count {df.shape[1]} in {url} "
            f"(expected {len(fmt.columns)} for {fmt.name} format)"
        )
    df.columns = fmt.columns
    return df


def _parse_for_area(
    df: pd.DataFrame,
    src: _UtilitySource,
    fmt: _FormatSpec,
    start: date,
    end: date,
) -> list[_MixRow]:
    """Melt the wide DataFrame into long-format _MixRow entries."""
    if "DATE" not in df.columns or "TIME" not in df.columns:
        return []

    ts = pd.to_datetime(
        df["DATE"].astype(str) + " " + df["TIME"].astype(str),
        format="mixed",
        errors="coerce",
    )
    df = df.assign(_ts_jst=ts.dt.tz_localize("Asia/Tokyo"))
    df = df.dropna(subset=["_ts_jst"])
    df = df.assign(_ts_utc=df["_ts_jst"].dt.tz_convert("UTC"))

    mask = (df["_ts_utc"].dt.date >= start) & (df["_ts_utc"].dt.date < end)
    df = df.loc[mask].reset_index(drop=True)
    if df.empty:
        return []

    out: list[_MixRow] = []
    for _, row in df.iterrows():
        slot_start = row["_ts_utc"].to_pydatetime().replace(tzinfo=UTC)
        for header, code in fmt.fuel_map.items():
            if header not in df.columns:
                continue
            v_mw = _parse_value_to_mw(row.get(header), fmt.mw_multiplier)
            if code == "pumped_storage" and v_mw is not None and v_mw < 0:
                v_mw = 0.0  # See module docstring.
            curt_header = next(
                (h for h, c in _CURTAIL_HEADER_TO_CODE.items() if c == code), None
            )
            curt_mw = (
                _parse_value_to_mw(row.get(curt_header), fmt.mw_multiplier)
                if curt_header else None
            )
            out.append(
                _MixRow(
                    area_code=src.area_code,
                    slot_start=slot_start,
                    fuel_code=code,
                    output_mw=v_mw,
                    curtailment_mw=curt_mw,
                )
            )
    return out


def _parse_value_to_mw(v, multiplier: float) -> float | None:
    try:
        if v is None or pd.isna(v) or str(v).strip() == "":
            return None
        return float(v) * multiplier
    except (TypeError, ValueError):
        return None


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    """Return a list of (year, month) pairs covering [start, end), inclusive of months touched."""
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= ((end - timedelta(days=1)).year, (end - timedelta(days=1)).month):
        out.append((y, m))
        m += 1
        if m == 13:
            y += 1
            m = 1
    return out


def ingest(start: date, end: date) -> IngestResult:
    """Fetch generation mix from each implemented utility for [start, end)."""
    with compute_run("ingest_generation_mix") as run:
        run.set_input({"start": start.isoformat(), "end": end.isoformat()})

        all_rows: list[_MixRow] = []
        errors: list[str] = []
        skipped: list[str] = []

        for area_code, src in _AREA_SOURCES.items():
            if not src.implemented:
                skipped.append(area_code)
                continue

            # 1) Per-month: try the fine-granule monthly URL. Track which
            # months had monthly coverage so we don't double-fetch via annual.
            covered_months: set[tuple[int, int]] = set()
            if src.monthly_url_pattern:
                for yyyy, mm in _months_between(start, end):
                    url = src.monthly_url_pattern.format(yyyy=yyyy, mm=mm)
                    try:
                        df = _fetch_csv(url, src.encoding, _MONTHLY_FMT)
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 404:
                            continue  # Expected for older months / pre-publication
                        errors.append(f"{area_code} {yyyy}-{mm:02d} monthly: {e!r}")
                        continue
                    except Exception as e:
                        errors.append(f"{area_code} {yyyy}-{mm:02d} monthly: {e!r}")
                        continue
                    all_rows.extend(_parse_for_area(df, src, _MONTHLY_FMT, start, end))
                    covered_months.add((yyyy, mm))

            # 2) Per-fiscal-year fallback: only fetch annual for FY whose
            # months aren't fully covered by monthly. Annual is hourly +
            # coarse thermal, so it's strictly less informative.
            if src.annual_url_pattern:
                requested_months = set(_months_between(start, end))
                missing_months = requested_months - covered_months
                fys_to_fetch = {
                    (y if m >= 4 else y - 1) for (y, m) in missing_months
                }
                for fy in sorted(fys_to_fetch):
                    url = src.annual_url_pattern.format(fy=fy)
                    try:
                        df = _fetch_csv(url, src.encoding, _ANNUAL_FMT)
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 404:
                            continue  # Annual file may not exist for current FY
                        errors.append(f"{area_code} FY{fy} annual: {e!r}")
                        continue
                    except Exception as e:
                        errors.append(f"{area_code} FY{fy} annual: {e!r}")
                        continue
                    # Restrict to months we don't already have via monthly.
                    rows_fy = _parse_for_area(df, src, _ANNUAL_FMT, start, end)
                    all_rows.extend(
                        r for r in rows_fy
                        if (r.slot_start.year, r.slot_start.month) not in covered_months
                    )

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select code, id from areas")
                code_to_area_id: dict[str, object] = dict(cur.fetchall())
                cur.execute("select code, id from fuel_types")
                code_to_fuel_id: dict[str, object] = dict(cur.fetchall())

        tuples = []
        for r in all_rows:
            area_id = code_to_area_id.get(r.area_code)
            fuel_id = code_to_fuel_id.get(r.fuel_code)
            if not area_id:
                if len(errors) < 50:
                    errors.append(f"unknown area code {r.area_code}")
                continue
            if not fuel_id:
                if len(errors) < 50:
                    errors.append(f"unknown fuel code {r.fuel_code}")
                continue
            tuples.append(
                (area_id, r.slot_start, fuel_id, r.output_mw, r.curtailment_mw, r.source)
            )

        inserted = 0
        if tuples:
            with connect() as conn:
                with conn.cursor() as cur:
                    advisory_lock(cur, "ingest_generation_mix")
                    for chunk in _chunks(tuples, 5000):
                        cur.executemany(
                            """
                            insert into generation_mix_actuals
                              (area_id, slot_start, fuel_type_id,
                               output_mw, curtailment_mw, source)
                            values (%s, %s, %s, %s, %s, %s)
                            on conflict (area_id, slot_start, fuel_type_id) do update set
                              output_mw = excluded.output_mw,
                              curtailment_mw = excluded.curtailment_mw,
                              source = excluded.source
                            """,
                            chunk,
                        )
                        inserted += cur.rowcount
                conn.commit()

        notes = None
        if skipped:
            implemented = sorted(a for a, s in _AREA_SOURCES.items() if s.implemented)
            notes = (
                f"M3 implements area={','.join(implemented)} only; "
                f"v2 follow-up rolls out {','.join(sorted(skipped))} "
                f"(per-utility CSVs documented in ingest/generation_mix.py::_AREA_SOURCES)."
            )

        result = IngestResult(
            source="ingest_generation_mix",
            window_start=start,
            window_end=end,
            rows_fetched=len(all_rows),
            rows_inserted=inserted,
            errors=errors[:50],
            notes=notes,
        )
        run.set_output(result.model_dump(mode="json", exclude={"errors"}))
        return result


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
