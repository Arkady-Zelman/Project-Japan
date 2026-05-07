"""Monthly fuel-price ingest from FRED (St. Louis Fed) CSV endpoints.

FRED publishes the World Bank's Pink Sheet commodity benchmarks as monthly
time-series via simple unauthenticated CSV URLs. No API key, no Excel parsing,
no rate-limit games. Three series cover what the stack model needs:

  - PNGASJPUSDM — Japan LNG (JKM equivalent), $/MMBtu, monthly
  - PCOALAUUSDM — Newcastle/Australia coal, $/MT, monthly
  - POILBREUSDM — Brent crude oil, $/bbl, monthly

These are the same World Bank Pink Sheet series the spec called for, just
reached through FRED's stable mirror instead of WB's churning xlsx URL.
Cadence is monthly across all three — sufficient for a stack model since
fuel costs move slowly relative to JEPX clearing prices.

Fuel-type mapping (`fuel_types.code` → FRED series):
  lng_ccgt, lng_steam → PNGASJPUSDM (JKM JP)
  coal                → PCOALAUUSDM (Newcastle)
  oil                 → POILBREUSDM (Brent)
  nuclear             → not ingested. Uranium price barely affects nuclear
                        SRMC at this resolution; `stack/srmc.py` uses a
                        constant fuel-cycle cost instead.

Schema target: fuel_prices(fuel_type_id, ts, price, unit, source, ingested_at)
PK is (fuel_type_id, ts, source). Source is 'fred_<series>' for traceability.
Unit field per spec §5: 'usd_mmbtu' | 'usd_bbl' | 'usd_t'.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock
from common.retry import retry_transient

from .models import IngestResult

_FRED_CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"


@dataclass(frozen=True)
class _SeriesSpec:
    """One FRED commodity series mapped to fuel_types.code(s)."""

    series_id: str          # e.g., 'PNGASJPUSDM'
    unit: str               # PG schema unit string per spec §5
    fuel_codes: tuple[str, ...]  # one or more fuel_types.code mapped to this series
    description: str        # human-friendly note


_SERIES: tuple[_SeriesSpec, ...] = (
    _SeriesSpec(
        series_id="PNGASJPUSDM",
        unit="usd_mmbtu",
        fuel_codes=("lng_ccgt", "lng_steam"),
        description="Japan LNG (JKM equivalent)",
    ),
    _SeriesSpec(
        series_id="PCOALAUUSDM",
        unit="usd_t",
        fuel_codes=("coal",),
        description="Newcastle Australia coal",
    ),
    _SeriesSpec(
        series_id="POILBREUSDM",
        unit="usd_bbl",
        fuel_codes=("oil",),
        description="Brent crude oil",
    ),
)


class _PriceObs(BaseModel):
    """One monthly observation. ts is the first-of-month at 00:00 UTC."""

    model_config = ConfigDict(extra="forbid")

    fuel_code: str
    ts: datetime
    price: float
    unit: str
    source: str  # 'fred_<series_id>'


@retry_transient
def _fetch_fred_csv(series_id: str) -> pd.DataFrame:
    """Download one FRED series as CSV. Returns a 2-column DataFrame.

    FRED returns the full series for a given series_id; we filter by date
    in the caller. The series contains every monthly observation back to
    the start of the series (1992 for these three series).
    """
    r = httpx.get(
        _FRED_CSV_BASE,
        params={"id": series_id},
        timeout=120,
        headers={"User-Agent": "jepx-storage-ingest/1.0"},
    )
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content))
    # FRED CSV header is `observation_date,<series_id>`. Normalize.
    if "observation_date" not in df.columns:
        raise ValueError(
            f"Unexpected FRED CSV layout for {series_id}: columns={list(df.columns)}"
        )
    df = df.rename(columns={series_id: "value"})
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce")
    df = df.dropna(subset=["observation_date"])
    return df


def _filter_window(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Restrict to observation_date in [start, end)."""
    if df.empty:
        return df
    mask = (df["observation_date"].dt.date >= start) & (df["observation_date"].dt.date < end)
    return df.loc[mask].reset_index(drop=True)


def _series_to_obs(df: pd.DataFrame, spec: _SeriesSpec) -> list[_PriceObs]:
    """Project one filtered FRED frame into _PriceObs entries.

    One observation per (fuel_code, month). FRED reports months as
    YYYY-MM-01; we normalize to UTC midnight at first-of-month.
    """
    out: list[_PriceObs] = []
    for _, row in df.iterrows():
        v = row.get("value")
        try:
            if v is None or pd.isna(v) or str(v).strip() == "":
                continue
            price = float(v)
        except (TypeError, ValueError):
            continue
        ts = row["observation_date"].to_pydatetime().replace(tzinfo=UTC)
        for fuel_code in spec.fuel_codes:
            out.append(
                _PriceObs(
                    fuel_code=fuel_code,
                    ts=ts,
                    price=price,
                    unit=spec.unit,
                    source=f"fred_{spec.series_id.lower()}",
                )
            )
    return out


def ingest(start: date, end: date) -> IngestResult:
    """Fetch every series, project to fuel_prices rows, UPSERT.

    Window semantics: observations whose `observation_date` falls in
    [start, end) are written. FRED's monthly cadence means partial-month
    windows still pull the most recent month-start present.
    """
    with compute_run("ingest_fuel_prices") as run:
        run.set_input({"start": start.isoformat(), "end": end.isoformat()})

        all_obs: list[_PriceObs] = []
        errors: list[str] = []

        for spec in _SERIES:
            try:
                df = _fetch_fred_csv(spec.series_id)
            except Exception as e:
                errors.append(f"{spec.series_id} fetch: {e!r}")
                continue
            df_window = _filter_window(df, start, end)
            all_obs.extend(_series_to_obs(df_window, spec))

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select code, id from fuel_types")
                code_to_fuel_id: dict[str, object] = dict(cur.fetchall())

        tuples = []
        for o in all_obs:
            fuel_id = code_to_fuel_id.get(o.fuel_code)
            if not fuel_id:
                if len(errors) < 50:
                    errors.append(f"unknown fuel code {o.fuel_code}")
                continue
            tuples.append((fuel_id, o.ts, o.price, o.unit, o.source))

        inserted = 0
        if tuples:
            with connect() as conn:
                with conn.cursor() as cur:
                    advisory_lock(cur, "ingest_fuel_prices")
                    for chunk in _chunks(tuples, 5000):
                        cur.executemany(
                            """
                            insert into fuel_prices
                              (fuel_type_id, ts, price, unit, source)
                            values (%s, %s, %s, %s, %s)
                            on conflict (fuel_type_id, ts, source) do update set
                              price = excluded.price,
                              unit = excluded.unit
                            """,
                            chunk,
                        )
                        inserted += cur.rowcount
                conn.commit()

        notes = (
            "Sources: FRED monthly mirrors of World Bank Pink Sheet — "
            "JKM JP (PNGASJPUSDM, $/MMBtu), Newcastle coal (PCOALAUUSDM, $/MT), "
            "Brent (POILBREUSDM, $/bbl). Nuclear fuel-cycle cost handled as "
            "a constant in stack/srmc.py."
        )

        result = IngestResult(
            source="ingest_fuel_prices",
            window_start=start,
            window_end=end,
            rows_fetched=len(all_obs),
            rows_inserted=inserted,
            errors=errors[:50],
            notes=notes,
        )
        run.set_output(result.model_dump(mode="json", exclude={"errors"}))
        return result


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
