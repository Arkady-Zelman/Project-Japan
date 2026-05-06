"""Hourly area demand from japanesepower.org `demand.csv`.

The v1 source is stale post-2024-03-31 — japanesepower.org's `demand.csv` was
last refreshed on that date and we don't get new data via this endpoint. Spec
§7.1 acknowledges this with the v2 OCCTO migration plan. For M3:

  - Backfill works: 2016-04-01 → 2024-03-31 of hourly demand for 9 areas.
  - Daily ingest after 2024-03-31 finds no new rows; `output.notes` flags it.

Schema target: `demand_actuals (area_id, slot_start, demand_mw, source, ingested_at)`
PK is `(area_id, slot_start)`. Note that the upstream is HOURLY, not half-hourly,
so each fetched hour produces one row at the top of the hour.
"""

from __future__ import annotations

import io
import os
from datetime import UTC, date, datetime

import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock
from common.retry import retry_transient

from ._areas import JAPOWER_AREA_MAP
from .models import IngestResult

_AREA_DEMAND_COLS = [
    "Hokkaido", "Tohoku", "Tokyo", "Chuubu", "Hokuriku",
    "Kansai", "Chuugoku", "Shikoku", "Kyushu",
]


class DemandRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_code: str
    slot_start: datetime
    demand_mw: float | None
    source: str = "japanesepower_csv"


@retry_transient
def _fetch_csv() -> pd.DataFrame:
    base = os.environ.get(
        "JAPANESEPOWER_BASE_URL", "https://japanesepower.org"
    ).rstrip("/")
    r = httpx.get(
        f"{base}/demand.csv",
        timeout=120,
        headers={"User-Agent": "jepx-storage-ingest/1.0"},
    )
    r.raise_for_status()
    return pd.read_csv(io.BytesIO(r.content))


def _melt_window(df: pd.DataFrame, start: date, end: date) -> list[DemandRow]:
    df = df.copy()
    # Combine Date + Time into a JST-naive timestamp, then convert to UTC.
    df["ts"] = pd.to_datetime(df["Date"] + " " + df["Time"], format="%Y-%m-%d %H:%M")
    df["ts"] = df["ts"].dt.tz_localize("Asia/Tokyo").dt.tz_convert("UTC")
    mask = (df["ts"].dt.date >= start) & (df["ts"].dt.date < end)
    df = df.loc[mask].reset_index(drop=True)
    if df.empty:
        return []

    out: list[DemandRow] = []
    for _, row in df.iterrows():
        slot_start = row["ts"].to_pydatetime().replace(tzinfo=UTC)
        for col in _AREA_DEMAND_COLS:
            code = JAPOWER_AREA_MAP[col]
            v = row.get(col)
            try:
                demand = None if pd.isna(v) else float(v)
            except (TypeError, ValueError):
                demand = None
            out.append(
                DemandRow(area_code=code, slot_start=slot_start, demand_mw=demand)
            )
    return out


def _upstream_latest(df: pd.DataFrame) -> date | None:
    """Return the most recent date present in the demand.csv contents.

    Lets the ingest job report exactly how fresh the upstream is on each run,
    so the dashboard `notes` field always reflects the current source state
    rather than a hardcoded cutoff in the codebase.
    """
    if df.empty:
        return None
    s = pd.to_datetime(df["Date"], errors="coerce")
    latest = s.max()
    return None if pd.isna(latest) else latest.date()


def ingest(start: date, end: date) -> IngestResult:
    with compute_run("ingest_demand") as run:
        run.set_input({"start": start.isoformat(), "end": end.isoformat()})

        df = _fetch_csv()
        upstream_latest = _upstream_latest(df)
        rows = _melt_window(df, start, end)

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select code, id from areas")
                code_to_id: dict[str, object] = dict(cur.fetchall())

        tuples = []
        errors: list[str] = []
        for r in rows:
            area_id = code_to_id.get(r.area_code)
            if not area_id:
                if len(errors) < 50:
                    errors.append(f"unknown area code {r.area_code}")
                continue
            tuples.append((area_id, r.slot_start, r.demand_mw, r.source))

        inserted = 0
        if tuples:
            with connect() as conn:
                with conn.cursor() as cur:
                    advisory_lock(cur, "ingest_demand")
                    for chunk in _chunks(tuples, 5000):
                        cur.executemany(
                            """
                            insert into demand_actuals
                              (area_id, slot_start, demand_mw, source)
                            values (%s, %s, %s, %s)
                            on conflict (area_id, slot_start) do update set
                              demand_mw = excluded.demand_mw,
                              source = excluded.source
                            """,
                            chunk,
                        )
                        inserted += cur.rowcount
                conn.commit()

        # Always report the upstream's latest available date — no hardcoded
        # cutoff. If the requested window starts past that date, we found
        # zero new rows and the operator can see *why* without reading code.
        notes = None
        if upstream_latest is not None:
            latest_iso = upstream_latest.isoformat()
            if not rows and start > upstream_latest:
                notes = (
                    f"upstream japanesepower.org/demand.csv last updated "
                    f"{latest_iso}; requested window {start.isoformat()} → "
                    f"{end.isoformat()} is past that. v2 OCCTO migration per "
                    f"spec §7.1 will close the gap."
                )
            else:
                notes = f"upstream latest available date: {latest_iso}"

        result = IngestResult(
            source="ingest_demand",
            window_start=start,
            window_end=end,
            rows_fetched=len(rows),
            rows_inserted=inserted,
            errors=errors,
            notes=notes,
        )
        run.set_output(result.model_dump(mode="json", exclude={"errors"}))
        return result


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
