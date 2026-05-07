"""Synthesize demand_actuals for the 4 deferred utilities (CB, KS, CG, KY)
when no public CSV is available for the requested window.

The 4 utilities listed in BUILD_SPEC §7.1.1 as "deferred" don't publish a
public area-supply CSV with recent monthly data:
  - CB (Chubu PG): no public fuel-mix CSV at all
  - KS (Kansai-TD): annual-only, post-FY2023 not published
  - CG (Chugoku NW): annual-only, post-FY2023 not published
  - KY (Kyushu NW): quarterly-only, post-FY2023 not published

Without demand we can't run the stack-clearing model for those areas. As an
explicit, clearly-tagged estimation: scale TK's actual demand by the
historical demand ratio each area held against TK during the overlap
window 2023-04 → 2024-03 (when all 9 areas had japanesepower.org data).

Ratios computed from the historical overlap (rounded):
  CB → 0.467  KS → 0.504  CG → 0.206  KY → 0.309

Source field: 'estimated_tk_ratio'. Visible in audit / dashboard. Replace
this when OCCTO direct ingest or per-utility legacy parsers are wired
(BUILD_SPEC §7.1.1 v2.5).

Usage:
    python -m stack.synthesize_demand --start 2026-05-01 --end 2026-05-08
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock

logger = logging.getLogger("stack.synthesize_demand")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# Computed from demand_actuals historical overlap 2023-04 → 2024-03.
# Refresh annually if the fleet shifts materially.
#
# TH (Tohoku) is included as a fallback because the upstream CSV typically
# lags by 1-2 months; when real data lands the regular `ingest_demand`
# UPSERT (without source filter) takes precedence, while our synth UPSERT
# only writes when source='estimated_tk_ratio' or null — two-way safe.
_TK_RATIO: dict[str, float] = {
    "CB": 0.4670,
    "KS": 0.5036,
    "CG": 0.2064,
    "KY": 0.3088,
    "TH": 0.2869,
}


def synthesize(start: date, end: date) -> dict:
    with compute_run("synthesize_demand") as run:
        run.set_input({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "areas": list(_TK_RATIO.keys()),
            "ratios": _TK_RATIO,
        })

        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select code, id::text from areas")
                code_to_area_id: dict[str, str] = dict(cur.fetchall())

                # Pull TK demand within window once.
                tk_id = code_to_area_id.get("TK")
                if not tk_id:
                    raise RuntimeError("TK area not found")
                cur.execute(
                    "select slot_start, demand_mw from demand_actuals "
                    "where area_id=%s and slot_start >= %s and slot_start < %s",
                    (tk_id, datetime.combine(start, datetime.min.time()),
                     datetime.combine(end, datetime.min.time())),
                )
                tk_rows = cur.fetchall()
                if not tk_rows:
                    run.set_output({"skipped": "no TK demand in window"})
                    return {"inserted": 0}

                inserted_per_area: dict[str, int] = {}
                advisory_lock(cur, "synthesize_demand")
                for area_code, ratio in _TK_RATIO.items():
                    area_id = code_to_area_id.get(area_code)
                    if not area_id:
                        continue
                    payload = [
                        (area_id, slot, float(tk_demand) * ratio if tk_demand is not None else None,
                         "estimated_tk_ratio")
                        for slot, tk_demand in tk_rows
                    ]
                    cur.executemany(
                        """
                        insert into demand_actuals
                          (area_id, slot_start, demand_mw, source)
                        values (%s, %s, %s, %s)
                        on conflict (area_id, slot_start) do update set
                          demand_mw = excluded.demand_mw,
                          source = excluded.source
                        where demand_actuals.source = 'estimated_tk_ratio'
                          or demand_actuals.source is null
                        """,
                        payload,
                    )
                    inserted_per_area[area_code] = len(payload)
                conn.commit()

        out = {"per_area": inserted_per_area, "total": sum(inserted_per_area.values())}
        run.set_output(out)
        logger.info("synthesized %s", out)
        return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m stack.synthesize_demand")
    p.add_argument("--start", required=True, type=date.fromisoformat)
    p.add_argument("--end", required=True, type=date.fromisoformat)
    args = p.parse_args(argv)
    synthesize(args.start, args.end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
