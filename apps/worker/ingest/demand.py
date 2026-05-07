"""Hourly area demand from per-utility area-supply CSVs (primary) +
japanesepower.org `demand.csv` (fallback for utilities not yet on _area_supply).

After M4 Phase 0:

  - 5 utilities (TK, HK, TH, HR, SK) flow through `_area_supply.fetch_for_area`.
    These get fresh demand data per-utility going forward (FY2024-04+ for
    HK/TH/HR/SK; full historical for TK).
  - 4 utilities (CB, KS, CG, KY) still pull from japanesepower.org's static
    CSV, which is stuck at 2024-03-31. v2.5 will roll out OCCTO direct or
    the per-utility legacy formats.

Schema target: `demand_actuals (area_id, slot_start, demand_mw, source, ingested_at)`
PK is `(area_id, slot_start)`. Both code paths UPSERT, so the source column
records which path won the most-recent write per (area, slot).
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

from . import _area_supply
from ._areas import JAPOWER_AREA_MAP
from .models import IngestResult

_JAPOWER_AREA_DEMAND_COLS = [
    "Hokkaido", "Tohoku", "Tokyo", "Chuubu", "Hokuriku",
    "Kansai", "Chuugoku", "Shikoku", "Kyushu",
]


class _DemandRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_code: str
    slot_start: datetime
    demand_mw: float | None
    source: str


# ---------------------------------------------------------------------------
# japanesepower.org fallback — covers the 4 utilities not yet on _area_supply
# ---------------------------------------------------------------------------


@retry_transient
def _fetch_japower_csv() -> pd.DataFrame:
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


def _melt_japower_window(
    df: pd.DataFrame, start: date, end: date, want_areas: set[str]
) -> list[_DemandRow]:
    """Melt japanesepower.org demand.csv → DemandRow entries for `want_areas`.

    `want_areas` is a set of 2-letter JEPX codes — we project the wide CSV
    to only the columns whose JEPX-code maps into the set, so the fallback
    doesn't double-write rows that the per-utility path already covers.
    """
    if df.empty:
        return []
    df = df.copy()
    df["ts"] = pd.to_datetime(df["Date"] + " " + df["Time"], format="%Y-%m-%d %H:%M")
    df["ts"] = df["ts"].dt.tz_localize("Asia/Tokyo").dt.tz_convert("UTC")
    mask = (df["ts"].dt.date >= start) & (df["ts"].dt.date < end)
    df = df.loc[mask].reset_index(drop=True)
    if df.empty:
        return []

    out: list[_DemandRow] = []
    for _, row in df.iterrows():
        slot_start = row["ts"].to_pydatetime().replace(tzinfo=UTC)
        for col in _JAPOWER_AREA_DEMAND_COLS:
            code = JAPOWER_AREA_MAP[col]
            if code not in want_areas:
                continue
            v = row.get(col)
            try:
                demand = None if pd.isna(v) else float(v)
            except (TypeError, ValueError):
                demand = None
            out.append(
                _DemandRow(
                    area_code=code,
                    slot_start=slot_start,
                    demand_mw=demand,
                    source="japanesepower_csv",
                )
            )
    return out


def _japower_upstream_latest(df: pd.DataFrame) -> date | None:
    """Most recent date present in japanesepower.org's demand.csv contents."""
    if df.empty:
        return None
    s = pd.to_datetime(df["Date"], errors="coerce")
    latest = s.max()
    return None if pd.isna(latest) else latest.date()


# ---------------------------------------------------------------------------
# Per-utility _area_supply path — covers the 5 implemented utilities
# ---------------------------------------------------------------------------


def _fetch_per_utility_rows(start: date, end: date) -> tuple[list[_DemandRow], list[str]]:
    rows: list[_DemandRow] = []
    errors: list[str] = []
    for area_code in _area_supply.implemented_area_codes():
        as_rows, errs = _area_supply.fetch_for_area(area_code, start, end)
        errors.extend(errs[:10])
        for r in as_rows:
            rows.append(
                _DemandRow(
                    area_code=area_code,
                    slot_start=r.slot_start,
                    demand_mw=r.demand_mw,
                    source="tso_area_jukyu",
                )
            )
    return rows, errors


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def ingest(start: date, end: date) -> IngestResult:
    """Fetch demand from both paths for [start, end). Idempotent UPSERT."""
    with compute_run("ingest_demand") as run:
        run.set_input({"start": start.isoformat(), "end": end.isoformat()})

        # Per-utility primary path
        primary_rows, primary_errors = _fetch_per_utility_rows(start, end)
        primary_areas = set(_area_supply.implemented_area_codes())

        # japanesepower.org fallback for the 4 areas not in the primary set
        fallback_areas = {code for code in JAPOWER_AREA_MAP.values() if code not in primary_areas}
        fallback_rows: list[_DemandRow] = []
        fallback_notes_latest: date | None = None
        try:
            df = _fetch_japower_csv()
            fallback_notes_latest = _japower_upstream_latest(df)
            fallback_rows = _melt_japower_window(df, start, end, fallback_areas)
        except Exception as e:
            primary_errors.append(f"japanesepower fallback: {e!r}")

        all_rows = primary_rows + fallback_rows

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select code, id from areas")
                code_to_id: dict[str, object] = dict(cur.fetchall())

        tuples = []
        errors: list[str] = primary_errors[:25]
        for r in all_rows:
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

        # Notes: surface freshness for both paths so the dashboard reflects
        # what's actually in the upstream — no hardcoded cutoffs.
        notes_parts: list[str] = []
        notes_parts.append(
            f"primary={','.join(sorted(primary_areas))} via tso_area_jukyu; "
            f"fallback={','.join(sorted(fallback_areas))} via japanesepower_csv"
        )
        if fallback_notes_latest is not None:
            notes_parts.append(
                f"japanesepower upstream latest={fallback_notes_latest.isoformat()}"
            )
        notes = " | ".join(notes_parts)

        result = IngestResult(
            source="ingest_demand",
            window_start=start,
            window_end=end,
            rows_fetched=len(all_rows),
            rows_inserted=inserted,
            errors=errors,
            notes=notes,
        )
        run.set_output(result.model_dump(mode="json", exclude={"errors"}))
        return result


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
