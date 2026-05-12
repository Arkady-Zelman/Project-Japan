"""generator_availability ingest (M10C L9).

Pulls reactor status from NRA RSS + utility outage publications and writes
per-(generator_id, slot_start) `available_mw` rows. The stack engine
(`stack/build_curve.py`) prefers these rows over per-unit metadata or
fleet defaults.

NRA reactor status RSS endpoint: https://www.nra.go.jp/rss/jishin.xml
(verify URL at runtime — the operator may need to point at a different
NRA RSS depending on what's published).

Utility outage publications vary per company; this module ships a
TODO-stubbed parser per area. Operator iterates as URLs are confirmed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock

from .models import IngestResult

logger = logging.getLogger("ingest.generator_availability")


def ingest(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> IngestResult:
    """Ingest generator availability into the `generator_availability` table.

    v1 status: shell only — wires the compute_run audit row + advisory lock
    + UPSERT path, but the actual NRA RSS + utility outage parsers are
    TODO. The operator pastes URLs / fixes parsers as live data sources are
    confirmed.
    """
    if end is None:
        end = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if start is None:
        start = end - timedelta(days=7)

    with compute_run("ingest_generator_availability") as run:
        run.set_input({"start": start.isoformat(), "end": end.isoformat()})

        # TODO: implement NRA reactor RSS parsing + utility outage scraping.
        rows: list[tuple[str, datetime, float, str, str]] = []

        if not rows:
            run.set_output({
                "rows_inserted": 0,
                "notes": "no parsers implemented yet; operator must wire NRA + utility URLs",
            })
            return IngestResult(rows_inserted=0, notes="parsers TODO")

        with connect() as conn, conn.cursor() as cur:
            advisory_lock(cur, "ingest_generator_availability")
            cur.executemany(
                """
                insert into generator_availability
                  (generator_id, slot_start, available_mw, status, source)
                values (%s, %s, %s, %s, %s)
                on conflict (generator_id, slot_start) do update set
                  available_mw = excluded.available_mw,
                  status = excluded.status,
                  source = excluded.source
                """,
                rows,
            )
            conn.commit()

        run.set_output({"rows_inserted": len(rows)})
        return IngestResult(rows_inserted=len(rows), notes=None)
