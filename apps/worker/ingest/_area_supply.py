"""Per-utility "エリア需給実績" (area supply-demand) CSV scraper.

Each Japanese TSO publishes hourly/half-hourly area supply-demand records as
CSVs. The same file contains BOTH demand and per-fuel generation mix, so we
keep one shared fetcher here and let `ingest/demand.py` and
`ingest/generation_mix.py` consume the same parsed rows.

Three publication families exist across the 9 utilities. Phase 0 implements
only the **TEPCO-family monthly** format, which covers TK + 4 others going
forward (FY2024-04+). The other utilities' formats are tracked in
BUILD_SPEC §7.1.1 for v2.5 follow-up; the parser is structured so adding a
new family is mostly typing.

Coverage matrix (as of 2026-05-06):

    Code  Utility         Source impl in Phase 0   Window covered
    ----  --------------  ------------------------  ----------------------
    TK    TEPCO PG        annual + monthly          2016-04 → present
    HK    Hokkaido NW     monthly only              2024-04 → present
    TH    Tohoku NW       monthly only              2024-04 → present
    HR    Hokuriku NW     monthly (post-2024-04)    2024-04 → present
    SK    Yonden NW       monthly only              2024-04 → present
    KS    Kansai-TD       (annual-only, deferred)   —
    CG    Chugoku NW      (annual-only, deferred)   —
    KY    Kyushu NW       (quarterly-only, def.)    —
    CB    Chubu PG        (no public mix CSV)       —

For the 4 deferred utilities, demand still flows via japanesepower.org
(stuck at 2024-03-31). Generation mix is unavailable until either
(a) OCCTO publishes a unified successor or (b) we implement the per-utility
parsers for each of the legacy formats. Both are tracked outside M4.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict

from common.retry import retry_transient

# ---------------------------------------------------------------------------
# Per-utility configuration
# ---------------------------------------------------------------------------


class UtilitySource(BaseModel):
    """One utility's CSV publication endpoint(s)."""

    model_config = ConfigDict(extra="forbid")

    area_code: str
    name: str
    annual_url_pattern: str | None = None
    monthly_url_pattern: str | None = None
    # Per-day fallback for utilities (currently TH) whose monthly publication
    # lags by 1-2 months but who do publish daily realtime CSVs. Format
    # placeholders: `{yyyy}{mm:02d}{dd:02d}`.
    daily_url_pattern: str | None = None
    encoding: str = "cp932"
    implemented: bool = False


AREA_SOURCES: dict[str, UtilitySource] = {
    "TK": UtilitySource(
        area_code="TK",
        name="TEPCO PG",
        annual_url_pattern="https://www.tepco.co.jp/forecast/html/images/area-{fy}.csv",
        monthly_url_pattern=(
            "https://www.tepco.co.jp/forecast/html/images/eria_jukyu_{yyyy}{mm:02d}_03.csv"
        ),
        encoding="utf-8-sig",
        implemented=True,
    ),
    "HK": UtilitySource(
        area_code="HK",
        name="Hokkaido NW",
        monthly_url_pattern=(
            "https://www.hepco.co.jp/network/con_service/public_document/"
            "supply_demand_results/csv/eria_jukyu_{yyyy}{mm:02d}_01.csv"
        ),
        encoding="cp932",
        implemented=True,
    ),
    "TH": UtilitySource(
        area_code="TH",
        name="Tohoku NW",
        monthly_url_pattern=(
            "https://setsuden.nw.tohoku-epco.co.jp/common/demand/"
            "eria_jukyu_{yyyy}{mm:02d}_02.csv"
        ),
        daily_url_pattern=(
            "https://setsuden.nw.tohoku-epco.co.jp/common/demand/realtime_jukyu/"
            "realtime_jukyu_{yyyy}{mm:02d}{dd:02d}_02.csv"
        ),
        encoding="cp932",
        implemented=True,
    ),
    "HR": UtilitySource(
        area_code="HR",
        name="Hokuriku NW",
        monthly_url_pattern=(
            "https://www.rikuden.co.jp/nw/denki-yoho/csv/"
            "eria_jukyu_{yyyy}{mm:02d}_05.csv"
        ),
        encoding="cp932",
        implemented=True,
    ),
    "SK": UtilitySource(
        area_code="SK",
        name="Yonden NW",
        monthly_url_pattern=(
            "https://www.yonden.co.jp/nw/supply_demand/csv/"
            "eria_jukyu_{yyyy}{mm:02d}_08.csv"
        ),
        encoding="cp932",
        implemented=True,
    ),
    # M10C L4: 4 deferred utilities now wired with verified URLs. Each URL
    # was confirmed by inspecting the utility's frontend JavaScript and
    # fetching a sample monthly CSV. Column counts dispatch to V1 (20-col)
    # or V2 (22-col) format automatically via `_pick_monthly_fmt`.
    #
    # CB: served by a PHP proxy. Format V2 (22 cols).
    # KS: filename-listed in `interchange/.../filelist.json`. Format V1 (20 cols).
    # CG: filename built in `js/script_eriajukyu_1.js`. Format V2 (22 cols).
    # KY: direct csv path under td_area_jukyu/. Format V1 (20 cols).
    "CB": UtilitySource(
        area_code="CB",
        name="Chubu PG",
        monthly_url_pattern=(
            "https://powergrid.chuden.co.jp/denkiyoho/resource/php/getCsv.php"
            "?file=eria_jukyu_{yyyy}{mm:02d}_04.csv"
        ),
        encoding="cp932",
        implemented=True,
    ),
    "KS": UtilitySource(
        area_code="KS",
        name="Kansai-TD",
        monthly_url_pattern=(
            "https://www.kansai-td.co.jp/interchange/denkiyoho/area-performance/"
            "eria_jukyu_{yyyy}{mm:02d}_06.csv"
        ),
        encoding="cp932",
        implemented=True,
    ),
    "CG": UtilitySource(
        area_code="CG",
        name="Chugoku NW",
        monthly_url_pattern=(
            "https://www.energia.co.jp/nw/jukyuu/sys/"
            "eria_jukyu_{yyyy}{mm:02d}_07.csv"
        ),
        encoding="cp932",
        implemented=True,
    ),
    "KY": UtilitySource(
        area_code="KY",
        name="Kyushu NW",
        monthly_url_pattern=(
            "https://www.kyuden.co.jp/td_area_jukyu/csv/"
            "eria_jukyu_{yyyy}{mm:02d}_09.csv"
        ),
        encoding="cp932",
        implemented=True,
    ),
}


# ---------------------------------------------------------------------------
# Format specs — describe how to parse one publication style
# ---------------------------------------------------------------------------


class FormatSpec(BaseModel):
    """How to read one CSV publication style."""

    model_config = ConfigDict(extra="forbid")

    name: str                   # 'annual' or 'monthly_tepco_family'
    skiprows: int               # Header rows to drop before reading
    columns: list[str]          # Column names assigned positionally
    fuel_map: dict[str, str]    # CSV header → fuel_types.code
    mw_multiplier: float        # Cell × this = MW. 10.0 for 万kWh/hr, 1.0 for MW.


# Annual file: 3 noise rows (unit + 2-row broken header), then hourly data
# in 万kWh-per-hour. Layout verified on TEPCO area-2023.csv.
_ANNUAL_FMT = FormatSpec(
    name="annual",
    skiprows=3,
    columns=[
        "DATE", "TIME", "demand",
        "原子力", "火力", "水力", "地熱", "バイオマス",
        "太陽光発電実績", "太陽光出力制御量",
        "風力発電実績", "風力出力制御量",
        "揚水", "連系線", "合計",
    ],
    fuel_map={
        "原子力": "nuclear",
        "火力": "lng_ccgt",  # Coarse: combined thermal. See generation_mix.py docstring.
        "水力": "hydro",
        "地熱": "geothermal",
        "バイオマス": "biomass",
        "太陽光発電実績": "solar",
        "風力発電実績": "wind",
        "揚水": "pumped_storage",
    },
    mw_multiplier=10.0,
)


# Monthly TEPCO-family file (v1, 20 cols): used by all 5 implemented utilities
# from 2024-04 through their respective format-migration dates. 1 noise row +
# 1 actual single-row header. 30-min granule. Values in MW. Fine thermal
# split + battery.
_MONTHLY_TEPCO_FMT = FormatSpec(
    name="monthly_tepco_family",
    skiprows=2,
    columns=[
        "DATE", "TIME", "demand",
        "原子力", "火力(LNG)", "火力(石炭)", "火力(石油)", "火力(その他)",
        "水力", "地熱", "バイオマス",
        "太陽光発電実績", "太陽光出力制御量",
        "風力発電実績", "風力出力制御量",
        "揚水", "蓄電池", "連系線", "その他", "合計",
    ],
    fuel_map={
        "原子力": "nuclear",
        "火力(LNG)": "lng_ccgt",
        "火力(石炭)": "coal",
        "火力(石油)": "oil",
        "水力": "hydro",
        "地熱": "geothermal",
        "バイオマス": "biomass",
        "太陽光発電実績": "solar",
        "風力発電実績": "wind",
        "揚水": "pumped_storage",
        "蓄電池": "battery",
    },
    mw_multiplier=1.0,
)


# Monthly TEPCO-family file (v2, 22 cols): adds `火力出力制御量` and
# `バイオマス出力制御量` curtailment columns. Migrated at different dates
# per utility (HK: 2025-04, HR: 2026-01, TH: 2026-03). The new curtailment
# columns aren't currently mapped — generation_mix_actuals only carries
# solar/wind curtailment. Thermal/biomass curtailment lives in the spare
# columns until a schema migration adds dedicated targets.
_MONTHLY_TEPCO_FMT_V2 = FormatSpec(
    name="monthly_tepco_family_v2",
    skiprows=2,
    columns=[
        "DATE", "TIME", "demand",
        "原子力",
        "火力(LNG)", "火力(石炭)", "火力(石油)", "火力(その他)", "火力出力制御量",
        "水力", "地熱", "バイオマス", "バイオマス出力制御量",
        "太陽光発電実績", "太陽光出力制御量",
        "風力発電実績", "風力出力制御量",
        "揚水", "蓄電池", "連系線", "その他", "合計",
    ],
    fuel_map={
        "原子力": "nuclear",
        "火力(LNG)": "lng_ccgt",
        "火力(石炭)": "coal",
        "火力(石油)": "oil",
        "水力": "hydro",
        "地熱": "geothermal",
        "バイオマス": "biomass",
        "太陽光発電実績": "solar",
        "風力発電実績": "wind",
        "揚水": "pumped_storage",
        "蓄電池": "battery",
    },
    mw_multiplier=1.0,
)


# Pick the right monthly FormatSpec by column count. Returns None if neither matches.
def _pick_monthly_fmt(num_cols: int) -> FormatSpec | None:
    if num_cols == len(_MONTHLY_TEPCO_FMT.columns):
        return _MONTHLY_TEPCO_FMT
    if num_cols == len(_MONTHLY_TEPCO_FMT_V2.columns):
        return _MONTHLY_TEPCO_FMT_V2
    return None


# Curtailment columns map onto the same fuel as the actual-output column.
_CURTAIL_HEADER_TO_CODE: dict[str, str] = {
    "太陽光出力制御量": "solar",
    "風力出力制御量": "wind",
}


# ---------------------------------------------------------------------------
# Output type — neutral row consumed by both demand.py and generation_mix.py
# ---------------------------------------------------------------------------


class AreaSupplyRow(BaseModel):
    """One slot of one area's supply-demand record.

    `fuel_outputs` keys are `fuel_types.code` values; values are MW averages
    for the slot. `curtailments` mirrors but holds positive curtailment MW.
    `demand_mw` is the area's metered demand for the slot.
    """

    model_config = ConfigDict(extra="forbid")

    area_code: str
    slot_start: datetime
    demand_mw: float | None
    fuel_outputs: dict[str, float | None]
    curtailments: dict[str, float | None]
    source_format: str  # 'annual' | 'monthly_tepco_family' — for audit


# ---------------------------------------------------------------------------
# HTTP fetch + parsing
# ---------------------------------------------------------------------------


@retry_transient
def _fetch_text(url: str, encoding: str) -> str:
    """Download a CSV body as decoded text. Retries transient errors."""
    r = httpx.get(url, timeout=120, headers={"User-Agent": "jepx-storage-ingest/1.0"})
    r.raise_for_status()
    return r.content.decode(encoding, errors="replace")


@lru_cache(maxsize=128)
def _fetch_text_cached(url: str, encoding: str) -> str:
    """Process-local cache so demand.py and generation_mix.py don't double-fetch.

    `ingest_daily` runs both sources in the same Modal container; without this
    cache each shared CSV is fetched twice. Cache is bounded so a long-running
    backfill doesn't blow memory; LRU eviction is fine because we iterate URLs
    monotonically by month.
    """
    return _fetch_text(url, encoding)


def _read_csv_with_format(text: str, fmt: FormatSpec, *, source_url: str) -> pd.DataFrame:
    """Parse text → DataFrame using the given FormatSpec.

    Both publication styles have header rows that don't fit pandas's
    multi-header parser cleanly. Fix: skip noise rows, read with header=None,
    assign column names from the FormatSpec.

    Raises ValueError if column count mismatches — surfaces format drift
    instead of silently ingesting garbage.
    """
    df = pd.read_csv(io.StringIO(text), skiprows=fmt.skiprows, header=None)
    if df.shape[1] != len(fmt.columns):
        raise ValueError(
            f"Unexpected column count {df.shape[1]} in {source_url} "
            f"(expected {len(fmt.columns)} for {fmt.name} format)"
        )
    df.columns = fmt.columns
    return df


def _coerce_value_to_mw(v, multiplier: float) -> float | None:
    """Convert a CSV cell to MW, with the format's multiplier applied."""
    try:
        if v is None or pd.isna(v) or str(v).strip() == "":
            return None
        # Some utilities quote totals with thousand separators ("7,124"); strip them.
        s = str(v).replace(",", "")
        return float(s) * multiplier
    except (TypeError, ValueError):
        return None


def _parse_rows(
    df: pd.DataFrame,
    src: UtilitySource,
    fmt: FormatSpec,
    start: date,
    end: date,
) -> list[AreaSupplyRow]:
    """Melt one parsed DataFrame into AreaSupplyRow entries."""
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

    out: list[AreaSupplyRow] = []
    for _, row in df.iterrows():
        slot_start = row["_ts_utc"].to_pydatetime().replace(tzinfo=UTC)
        demand_mw = _coerce_value_to_mw(row.get("demand"), fmt.mw_multiplier)

        fuel_outputs: dict[str, float | None] = {}
        for header, code in fmt.fuel_map.items():
            if header not in df.columns:
                continue
            v_mw = _coerce_value_to_mw(row.get(header), fmt.mw_multiplier)
            if code == "pumped_storage" and v_mw is not None and v_mw < 0:
                v_mw = 0.0  # Pump-up shows negative; record only generation direction.
            fuel_outputs[code] = v_mw

        curtailments: dict[str, float | None] = {}
        for curt_header, code in _CURTAIL_HEADER_TO_CODE.items():
            if curt_header in df.columns:
                curtailments[code] = _coerce_value_to_mw(
                    row.get(curt_header), fmt.mw_multiplier
                )

        out.append(
            AreaSupplyRow(
                area_code=src.area_code,
                slot_start=slot_start,
                demand_mw=demand_mw,
                fuel_outputs=fuel_outputs,
                curtailments=curtailments,
                source_format=fmt.name,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    """List of (year, month) pairs touching [start, end), inclusive of months touched."""
    out: list[tuple[int, int]] = []
    if end <= start:
        return out
    last = end - timedelta(days=1)
    y, m = start.year, start.month
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        m += 1
        if m == 13:
            y += 1
            m = 1
    return out


def fetch_for_area(
    area_code: str,
    start: date,
    end: date,
) -> tuple[list[AreaSupplyRow], list[str]]:
    """Fetch all supply-demand rows for `area_code` over [start, end).

    Returns (rows, errors). The implementation tries the monthly URL per
    calendar month first (richer + fresher), then falls back to the annual
    URL per fiscal-year for any months not covered. UPSERT in the caller
    handles any duplicates.

    Errors are non-fatal — a missing month gets a 404 and we move on. Only
    structural problems (unexpected column count, decode failure) abort the
    fetch for that file.
    """
    src = AREA_SOURCES.get(area_code)
    if src is None or not src.implemented:
        return [], [f"area_code={area_code} not implemented in _area_supply"]

    rows: list[AreaSupplyRow] = []
    errors: list[str] = []

    # 1) Monthly per-calendar-month
    covered_months: set[tuple[int, int]] = set()
    if src.monthly_url_pattern:
        for yyyy, mm in _months_between(start, end):
            url = src.monthly_url_pattern.format(yyyy=yyyy, mm=mm)
            try:
                text = _fetch_text_cached(url, src.encoding)
                # Some utilities migrated their schema mid-window (e.g. HEPCO
                # at 2025-04). Auto-detect by column count.
                probe = pd.read_csv(io.StringIO(text), skiprows=2, header=None, nrows=1)
                fmt = _pick_monthly_fmt(probe.shape[1])
                if fmt is None:
                    errors.append(
                        f"{area_code} {yyyy}-{mm:02d} monthly: unrecognized "
                        f"column count {probe.shape[1]} at {url}"
                    )
                    continue
                df = _read_csv_with_format(text, fmt, source_url=url)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue  # Pre-publication or out-of-archive month.
                errors.append(f"{area_code} {yyyy}-{mm:02d} monthly: {e!r}")
                continue
            except Exception as e:
                errors.append(f"{area_code} {yyyy}-{mm:02d} monthly: {e!r}")
                continue
            rows.extend(_parse_rows(df, src, fmt, start, end))
            covered_months.add((yyyy, mm))

    # 1b) Daily per-day fallback — only used when monthly didn't cover the
    # month (e.g. Tohoku's monthly publication lags fiscal-year-end). One
    # request per JST day in the window; tolerate 404s for days that haven't
    # been published yet.
    if src.daily_url_pattern:
        requested_months_before_daily = set(_months_between(start, end))
        missing_months_for_daily = requested_months_before_daily - covered_months
        if missing_months_for_daily:
            day = start
            while day < end:
                month_key = (day.year, day.month)
                if month_key not in missing_months_for_daily:
                    day += timedelta(days=1)
                    continue
                url = src.daily_url_pattern.format(
                    yyyy=day.year, mm=day.month, dd=day.day,
                )
                try:
                    text = _fetch_text_cached(url, src.encoding)
                    probe = pd.read_csv(io.StringIO(text), skiprows=2, header=None, nrows=1)
                    fmt = _pick_monthly_fmt(probe.shape[1])
                    if fmt is None:
                        errors.append(
                            f"{area_code} {day.isoformat()} daily: unrecognized "
                            f"column count {probe.shape[1]} at {url}"
                        )
                        day += timedelta(days=1)
                        continue
                    df = _read_csv_with_format(text, fmt, source_url=url)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code != 404:
                        errors.append(f"{area_code} {day.isoformat()} daily: {e!r}")
                    day += timedelta(days=1)
                    continue
                except Exception as e:
                    errors.append(f"{area_code} {day.isoformat()} daily: {e!r}")
                    day += timedelta(days=1)
                    continue
                rows.extend(_parse_rows(df, src, fmt, day, day + timedelta(days=1)))
                day += timedelta(days=1)

    # 2) Annual per-fiscal-year, only for months not yet covered.
    if src.annual_url_pattern:
        requested_months = set(_months_between(start, end))
        missing_months = requested_months - covered_months
        fys_to_fetch = {(y if m >= 4 else y - 1) for (y, m) in missing_months}
        for fy in sorted(fys_to_fetch):
            url = src.annual_url_pattern.format(fy=fy)
            try:
                text = _fetch_text_cached(url, src.encoding)
                df = _read_csv_with_format(text, _ANNUAL_FMT, source_url=url)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue  # Annual file may not exist yet for current FY.
                errors.append(f"{area_code} FY{fy} annual: {e!r}")
                continue
            except Exception as e:
                errors.append(f"{area_code} FY{fy} annual: {e!r}")
                continue
            # Restrict to months we don't already have via monthly.
            rows_fy = _parse_rows(df, src, _ANNUAL_FMT, start, end)
            rows.extend(
                r for r in rows_fy
                if (r.slot_start.year, r.slot_start.month) not in covered_months
            )

    return rows, errors


def implemented_area_codes() -> list[str]:
    """The 5-area subset whose data flows through this module in Phase 0."""
    return [code for code, src in AREA_SOURCES.items() if src.implemented]
