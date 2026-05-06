"""Refresh the `jp_holidays` table for a forward window.

Unlike the time-series ingest jobs, this one doesn't fetch from a remote API —
the `holidays` Python package ships with the calendar baked in. We just call
`seed.load_reference.build_holidays` for the requested year window and UPSERT.

Daily runs are wasteful but harmless (idempotent UPSERT). The Modal cron is
annual on Jan 1 to pick up the next year. CLI invocations can pass a wider
range when needed.
"""

from __future__ import annotations

from datetime import date

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock
from seed.load_reference import build_holidays

from .models import IngestResult


def ingest(start: date, end: date) -> IngestResult:
    """Refresh jp_holidays covering [start, end) — defaults to whole years.

    The Pydantic JpHoliday model lives in seed.models and is used inside
    build_holidays(). We re-use that path verbatim.
    """
    with compute_run("ingest_holidays") as run:
        run.set_input({"start": start.isoformat(), "end": end.isoformat()})

        rows = build_holidays(start.year, end.year)

        inserted = 0
        if rows:
            with connect() as conn:
                with conn.cursor() as cur:
                    advisory_lock(cur, "ingest_holidays")
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
                    inserted = cur.rowcount
                conn.commit()

        result = IngestResult(
            source="ingest_holidays",
            window_start=start,
            window_end=end,
            rows_fetched=len(rows),
            rows_inserted=inserted,
        )
        run.set_output(result.model_dump(mode="json", exclude={"errors"}))
        return result
