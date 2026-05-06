"""JEPX day-ahead spot prices from japanesepower.org.

The upstream is one big CSV (`jepxSpot.csv`, ~40 MB, half-hourly back to 2010)
in wide format: each row has 9 area-price columns plus a system price and
volume columns. We melt wide → long so it matches the `jepx_spot_prices`
schema (one row per area × slot).

Daily ingest fetches the full file and filters to [start, end). That's
wasteful in bytes but simple, idempotent, and the file fits in memory.
For backfill across 5+ years the same code path works — we just pass a wider
window.
"""

from __future__ import annotations

import io
import os
from datetime import UTC, date, datetime, timedelta

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


class JepxPriceRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_code: str
    slot_start: datetime
    slot_end: datetime
    price_jpy_kwh: float | None
    sell_volume_mwh: float | None
    buy_volume_mwh: float | None
    contract_volume_mwh: float | None
    auction_type: str = "day_ahead"
    source: str = "japanesepower_csv"


@retry_transient
def _fetch_csv() -> pd.DataFrame:
    base = os.environ.get(
        "JAPANESEPOWER_BASE_URL", "https://japanesepower.org"
    ).rstrip("/")
    r = httpx.get(
        f"{base}/jepxSpot.csv",
        timeout=120,
        headers={"User-Agent": "jepx-storage-ingest/1.0"},
    )
    r.raise_for_status()
    return pd.read_csv(io.BytesIO(r.content))


def _melt_window(df: pd.DataFrame, start: date, end: date) -> list[JepxPriceRow]:
    """Filter to [start, end), melt wide → long, build Pydantic rows."""
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], utc=False)
    # Treat datetimes as JST (Asia/Tokyo) — they are.
    df["datetime"] = df["datetime"].dt.tz_localize("Asia/Tokyo").dt.tz_convert("UTC")
    mask = (df["datetime"].dt.date >= start) & (df["datetime"].dt.date < end)
    df = df.loc[mask].reset_index(drop=True)
    if df.empty:
        return []

    out: list[JepxPriceRow] = []
    for _, row in df.iterrows():
        slot_start = row["datetime"].to_pydatetime().replace(tzinfo=UTC)
        slot_end = slot_start + timedelta(minutes=30)
        sell_vol = _kwh_to_mwh(row.get("Sell Bid Volume kWh"))
        buy_vol = _kwh_to_mwh(row.get("Buy Bid Volume kWh"))
        contract_vol = _kwh_to_mwh(row.get("Contracted Total Volume kWh"))

        for col, code in JAPOWER_AREA_MAP.items():
            if code == "SYS":
                price = _f(row.get("System Price Yen/kWh"))
            else:
                price = _f(row.get(f"{col} Yen/kWh"))
            out.append(
                JepxPriceRow(
                    area_code=code,
                    slot_start=slot_start,
                    slot_end=slot_end,
                    price_jpy_kwh=price,
                    sell_volume_mwh=sell_vol,
                    buy_volume_mwh=buy_vol,
                    contract_volume_mwh=contract_vol,
                )
            )
    return out


def _f(v) -> float | None:
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _kwh_to_mwh(v) -> float | None:
    f = _f(v)
    return None if f is None else f / 1000.0


def ingest(start: date, end: date) -> IngestResult:
    with compute_run("ingest_jepx_prices") as run:
        run.set_input({"start": start.isoformat(), "end": end.isoformat()})

        df = _fetch_csv()
        rows = _melt_window(df, start, end)

        # Resolve area codes once
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
            tuples.append(
                (
                    area_id, r.slot_start, r.slot_end,
                    r.price_jpy_kwh,
                    r.sell_volume_mwh, r.buy_volume_mwh, r.contract_volume_mwh,
                    r.auction_type, r.source,
                )
            )

        inserted = 0
        if tuples:
            with connect() as conn:
                with conn.cursor() as cur:
                    advisory_lock(cur, "ingest_jepx_prices")
                    # Batch in chunks of 5000 to keep statements digestible
                    for chunk in _chunks(tuples, 5000):
                        cur.executemany(
                            """
                            insert into jepx_spot_prices
                              (area_id, slot_start, slot_end, price_jpy_kwh,
                               sell_volume_mwh, buy_volume_mwh, contract_volume_mwh,
                               auction_type, source)
                            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            on conflict (area_id, slot_start, auction_type) do update set
                              price_jpy_kwh = excluded.price_jpy_kwh,
                              sell_volume_mwh = excluded.sell_volume_mwh,
                              buy_volume_mwh = excluded.buy_volume_mwh,
                              contract_volume_mwh = excluded.contract_volume_mwh,
                              source = excluded.source,
                              slot_end = excluded.slot_end
                            """,
                            chunk,
                        )
                        inserted += cur.rowcount
                conn.commit()

        result = IngestResult(
            source="ingest_jepx_prices",
            window_start=start,
            window_end=end,
            rows_fetched=len(rows),
            rows_inserted=inserted,
            errors=errors,
        )
        run.set_output(result.model_dump(mode="json", exclude={"errors"}))
        return result


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
