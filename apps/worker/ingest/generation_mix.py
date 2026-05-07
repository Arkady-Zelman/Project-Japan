"""Hourly generation mix by fuel type — pulled from per-utility area-supply CSVs.

The CSV fetch + parse lives in `ingest/_area_supply.py` (shared with `demand.py`).
This module consumes `AreaSupplyRow`s and projects them to long-format
`generation_mix_actuals` rows keyed on (area, slot, fuel).

Coverage in Phase 0: 5 utilities (TK, HK, TH, HR, SK). Other 4 utilities
(CB, KS, CG, KY) deferred — see BUILD_SPEC §7.1.1 and `_area_supply.py`
docstring for the data-availability matrix.

Fuel-bucket mapping is in `_area_supply.py::FormatSpec.fuel_map`. The annual
format has a coarse single-thermal `火力` column that we map to `lng_ccgt`
as a best-effort proxy; the monthly format has the fine LNG/coal/oil split.
"""

from __future__ import annotations

from datetime import date

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock

from . import _area_supply
from .models import IngestResult


def ingest(start: date, end: date) -> IngestResult:
    """Fetch generation mix from every implemented utility for [start, end)."""
    with compute_run("ingest_generation_mix") as run:
        run.set_input({"start": start.isoformat(), "end": end.isoformat()})

        all_rows: list[tuple] = []
        errors: list[str] = []
        rows_fetched = 0
        skipped: list[str] = []

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select code, id from areas")
                code_to_area_id: dict[str, object] = dict(cur.fetchall())
                cur.execute("select code, id from fuel_types")
                code_to_fuel_id: dict[str, object] = dict(cur.fetchall())

        for area_code, src in _area_supply.AREA_SOURCES.items():
            if not src.implemented:
                skipped.append(area_code)
                continue
            area_id = code_to_area_id.get(area_code)
            if not area_id:
                errors.append(f"unknown area code {area_code}")
                continue

            rows, fetch_errors = _area_supply.fetch_for_area(area_code, start, end)
            errors.extend(fetch_errors[:25])
            rows_fetched += len(rows)

            for r in rows:
                for fuel_code, mw in r.fuel_outputs.items():
                    fuel_id = code_to_fuel_id.get(fuel_code)
                    if not fuel_id:
                        if len(errors) < 50:
                            errors.append(f"unknown fuel code {fuel_code}")
                        continue
                    curt_mw = r.curtailments.get(fuel_code)
                    all_rows.append(
                        (area_id, r.slot_start, fuel_id, mw, curt_mw, "tso_area_jukyu")
                    )

        inserted = 0
        if all_rows:
            with connect() as conn:
                with conn.cursor() as cur:
                    advisory_lock(cur, "ingest_generation_mix")
                    for chunk in _chunks(all_rows, 5000):
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
            implemented = sorted(_area_supply.implemented_area_codes())
            notes = (
                f"Phase 0 implemented={','.join(implemented)}; "
                f"deferred={','.join(sorted(skipped))} "
                f"(see BUILD_SPEC §7.1.1 — different format families / no public CSV)."
            )

        result = IngestResult(
            source="ingest_generation_mix",
            window_start=start,
            window_end=end,
            rows_fetched=rows_fetched,
            rows_inserted=inserted,
            errors=errors[:50],
            notes=notes,
        )
        run.set_output(result.model_dump(mode="json", exclude={"errors"}))
        return result


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
