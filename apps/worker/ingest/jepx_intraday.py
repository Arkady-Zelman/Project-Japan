"""JEPX 1h-ahead (intraday) market ingest (M10C L6).

The upstream `jepxIntra.csv` from japanesepower.org follows the same wide
layout as `jepxSpot.csv` — half-hourly rows × 9 area-price columns. We melt
wide → long and UPSERT into `jepx_intraday_prices`.

Cron capacity note (apps/worker/CLAUDE.md): the Modal free tier holds 5
schedules. Currently 6 ingest crons exist; the operator should either
fold this into `ingest_jepx_prices` (one Modal function calling two
ingest paths) or upgrade Modal tier.
"""

from __future__ import annotations

import io
import os
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock
from common.retry import retry_transient

from ._areas import JAPOWER_AREA_MAP
from .models import IngestResult

_AREA_PRICE_COLS = [
    "System", "Hokkaido", "Tohoku", "Tokyo", "Chuubu",
    "Hokuriku", "Kansai", "Chuugoku", "Shikoku", "Kyushu",
]


class JepxIntradayRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_code: str
    slot_start: datetime
    slot_end: datetime
    price_jpy_kwh: float | None
    volume_mwh: float | None
    source: str = "japanesepower_csv"


@retry_transient
def _fetch_csv() -> pd.DataFrame:
    base = os.environ.get(
        "JAPANESEPOWER_BASE_URL", "https://japanesepower.org"
    ).rstrip("/")
    # Endpoint name is best-effort; operator may need to confirm the actual
    # path on japanesepower.org (the day-ahead file is jepxSpot.csv).
    r = httpx.get(
        f"{base}/jepxIntra.csv",
        timeout=120,
        headers={"User-Agent": "jepx-storage-ingest/1.0"},
    )
    r.raise_for_status()
    return pd.read_csv(io.BytesIO(r.content))


def ingest(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> IngestResult:
    if end is None:
        end = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if start is None:
        start = end - timedelta(days=2)

    with compute_run("ingest_jepx_intraday") as run:
        run.set_input({
            "start": start.isoformat(),
            "end": end.isoformat(),
        })

        df = _fetch_csv()
        # Best-effort melt: column names match the daily file's convention.
        if "Date" not in df.columns or "Slot" not in df.columns:
            run.set_output({"skipped": "unexpected_csv_format", "cols": list(df.columns)[:6]})
            return IngestResult(rows_inserted=0, notes="upstream format changed; ingest skipped")

        # Build slot_start from Date + Slot (1..48, each = 30min).
        df["slot_start"] = pd.to_datetime(df["Date"]) + pd.to_timedelta(
            (df["Slot"].astype(int) - 1) * 30, unit="min"
        )
        df = df[(df["slot_start"] >= start) & (df["slot_start"] < end)]

        rows: list[JepxIntradayRow] = []
        for _, r in df.iterrows():
            slot_start = r["slot_start"].to_pydatetime().replace(tzinfo=UTC)
            slot_end = slot_start + timedelta(minutes=30)
            for col in _AREA_PRICE_COLS:
                code = JAPOWER_AREA_MAP.get(col)
                if not code or col not in r:
                    continue
                price = r.get(col)
                vol_col = f"{col}_Vol"
                vol = r.get(vol_col) if vol_col in r else None
                rows.append(
                    JepxIntradayRow(
                        area_code=code,
                        slot_start=slot_start,
                        slot_end=slot_end,
                        price_jpy_kwh=float(price) if pd.notna(price) else None,
                        volume_mwh=float(vol) if vol is not None and pd.notna(vol) else None,
                    )
                )

        if not rows:
            run.set_output({"rows_inserted": 0, "notes": "no rows in window"})
            return IngestResult(rows_inserted=0, notes="no rows in window")

        with connect() as conn, conn.cursor() as cur:
            advisory_lock(cur, "ingest_jepx_intraday")
            # Resolve area_ids once.
            cur.execute("select code, id from areas")
            area_ids = {c: i for (c, i) in cur.fetchall()}
            data = [
                (
                    area_ids[r.area_code],
                    r.slot_start,
                    r.slot_end,
                    r.price_jpy_kwh,
                    r.volume_mwh,
                    r.source,
                )
                for r in rows
                if r.area_code in area_ids
            ]
            cur.executemany(
                """
                insert into jepx_intraday_prices
                  (area_id, slot_start, slot_end, price_jpy_kwh, volume_mwh, source)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (area_id, slot_start) do update set
                  slot_end = excluded.slot_end,
                  price_jpy_kwh = excluded.price_jpy_kwh,
                  volume_mwh = excluded.volume_mwh,
                  source = excluded.source
                """,
                data,
            )
            conn.commit()

        run.set_output({"rows_inserted": len(data), "areas": list({r.area_code for r in rows})})
        return IngestResult(rows_inserted=len(data), notes=None)
