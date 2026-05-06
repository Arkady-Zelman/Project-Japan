"""USD/JPY daily FX rates from Frankfurter (ECB-sourced, no API key).

Frankfurter exposes a date-range endpoint:

    GET https://api.frankfurter.dev/v1/{start}..{end}?base=USD&symbols=JPY

Response shape:
    { "amount": 1.0, "base": "USD", "start_date": "...", "end_date": "...",
      "rates": { "2024-01-02": {"JPY": 142.1}, "2024-01-03": {"JPY": 141.8}, ... } }

Frankfurter only returns business days; weekends and holidays are skipped
upstream. Our daily ingest is a no-op on those days, which is correct.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time

import httpx
from pydantic import BaseModel, ConfigDict

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock
from common.retry import retry_transient

from .models import IngestResult


class FxRateRow(BaseModel):
    """One row of `fx_rates`."""

    model_config = ConfigDict(extra="forbid")

    pair: str
    ts: datetime
    rate: float
    source: str = "frankfurter"


@retry_transient
def _fetch(start: date, end: date) -> dict[str, dict[str, float]]:
    """Fetch USD→JPY for [start, end). Returns {date_iso: {"JPY": rate}}."""
    base = os.environ.get("FRANKFURTER_BASE_URL", "https://api.frankfurter.dev")
    url = f"{base}/v1/{start.isoformat()}..{end.isoformat()}"
    r = httpx.get(url, params={"base": "USD", "symbols": "JPY"}, timeout=30)
    r.raise_for_status()
    return r.json().get("rates", {})


def ingest(start: date, end: date) -> IngestResult:
    """Fetch USD/JPY for [start, end), UPSERT into fx_rates."""
    with compute_run("ingest_fx") as run:
        run.set_input({"start": start.isoformat(), "end": end.isoformat()})

        raw = _fetch(start, end)

        rows: list[FxRateRow] = []
        errors: list[str] = []
        for date_iso, rates in raw.items():
            try:
                rows.append(
                    FxRateRow(
                        pair="USDJPY",
                        # Use 00:00 UTC of the quote date as the canonical timestamp.
                        ts=datetime.combine(
                            date.fromisoformat(date_iso), time(0, 0), tzinfo=UTC
                        ),
                        rate=float(rates["JPY"]),
                    )
                )
            except (KeyError, ValueError) as e:
                if len(errors) < 50:
                    errors.append(f"{date_iso}: {e!r}")

        inserted = 0
        if rows:
            with connect() as conn:
                with conn.cursor() as cur:
                    advisory_lock(cur, "ingest_fx")
                    cur.executemany(
                        """
                        insert into fx_rates (pair, ts, rate, source)
                        values (%s, %s, %s, %s)
                        on conflict (pair, ts, source) do update set rate = excluded.rate
                        """,
                        [(r.pair, r.ts, r.rate, r.source) for r in rows],
                    )
                    inserted = cur.rowcount
                conn.commit()

        result = IngestResult(
            source="ingest_fx",
            window_start=start,
            window_end=end,
            rows_fetched=len(raw),
            rows_inserted=inserted,
            errors=errors,
        )
        run.set_output(result.model_dump(mode="json", exclude={"errors"}))
        return result
