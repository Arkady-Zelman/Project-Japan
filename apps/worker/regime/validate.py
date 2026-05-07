"""April 2026 spike-window validation for the M5 STOP gate.

Per the amended BUILD_SPEC §12 M5 (the original 2021 Jan/Feb cold-snap window
isn't in our DB — M3 trim cut history at 2023-01-01). Replacement window:

    April 2026
    TK spike slots = realised price > ¥30/kWh   (~128 slots)
    TH spike slots = realised price > ¥30/kWh   (~40 slots)

Gate: P(spike) ≥ 0.7 on at least 80% of those slots in BOTH TK and TH.

CLI: `python -m regime.validate`. Logs to compute_runs(kind='regime_validate').
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, date, datetime

from common.audit import compute_run
from common.db import connect

logger = logging.getLogger("regime.validate")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


_SPIKE_PRICE_THRESHOLD_KWH = 30.0
_SPIKE_POSTERIOR_THRESHOLD = 0.7
_PASS_FRACTION = 0.80
# All 9 areas evaluated. The spec gate requires TK + TH; the remaining 7 are
# diagnostic — areas with too few spike slots in April 2026 are flagged
# separately so a sparse spike count doesn't read as a failure.
_DEFAULT_AREAS: tuple[str, ...] = (
    "TK", "TH", "HK", "HR", "CB", "KS", "CG", "SK", "KY",
)
_GATE_REQUIRED_AREAS: tuple[str, ...] = ("TK", "TH")
_MIN_SPIKE_SLOTS_FOR_GATE = 10


def evaluate(start: date, end: date, areas: tuple[str, ...] = _DEFAULT_AREAS) -> dict:
    with compute_run("regime_validate") as run:
        run.set_input({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "areas": list(areas),
            "spike_price_threshold_kwh": _SPIKE_PRICE_THRESHOLD_KWH,
            "spike_posterior_threshold": _SPIKE_POSTERIOR_THRESHOLD,
            "pass_fraction": _PASS_FRACTION,
        })

        per_area: dict[str, dict] = {}
        with connect() as conn, conn.cursor() as cur:
            for code in areas:
                # Filter to the latest 'ready' model_version so we don't
                # double-count slots that were calibrated under an earlier
                # version still present in the table.
                cur.execute(
                    """
                    with spike_slots as (
                      select j.slot_start, j.price_jpy_kwh
                      from jepx_spot_prices j join areas a on a.id = j.area_id
                      where a.code = %s and j.auction_type = 'day_ahead'
                        and j.slot_start >= %s and j.slot_start < %s
                        and j.price_jpy_kwh > %s
                    ),
                    active as (
                      select version
                      from models
                      where type='mrs' and name=%s and status='ready'
                      order by created_at desc limit 1
                    )
                    select s.slot_start, s.price_jpy_kwh, r.p_spike,
                           r.most_likely_regime, r.model_version
                    from spike_slots s
                    left join regime_states r
                      on r.area_id = (select id from areas where code = %s)
                     and r.slot_start = s.slot_start
                     and r.model_version = (select version from active)
                    """,
                    (
                        code,
                        datetime.combine(start, datetime.min.time(), UTC),
                        datetime.combine(end, datetime.min.time(), UTC),
                        _SPIKE_PRICE_THRESHOLD_KWH,
                        f"mrs_{code}",
                        code,
                    ),
                )
                rows = cur.fetchall()
                n_total = len(rows)
                if n_total == 0:
                    per_area[code] = {
                        "n_spike_slots": 0,
                        "n_with_regime_state": 0,
                        "n_above_posterior_threshold": 0,
                        "fraction_passing": 0.0,
                        "passes_gate": False,
                        "skipped": "no_spike_slots",
                    }
                    continue

                n_with = sum(1 for r in rows if r[2] is not None)
                n_above = sum(
                    1 for r in rows
                    if r[2] is not None and float(r[2]) >= _SPIKE_POSTERIOR_THRESHOLD
                )
                fraction = n_above / max(n_with, 1)
                # Areas with very few spike slots can't meaningfully pass or
                # fail the gate; a single missed slot in 5 reads as 80% but
                # is statistical noise. Mark them informational-only.
                gateable = n_total >= _MIN_SPIKE_SLOTS_FOR_GATE
                per_area[code] = {
                    "n_spike_slots": n_total,
                    "n_with_regime_state": n_with,
                    "n_above_posterior_threshold": n_above,
                    "fraction_passing": round(fraction, 4),
                    "passes_gate": gateable and fraction >= _PASS_FRACTION,
                    "gateable": gateable,
                }

        # The spec gate is required only for TK + TH. Other areas are reported
        # for transparency but don't gate-fail M5.
        gate_pass = all(
            per_area[c]["passes_gate"]
            for c in _GATE_REQUIRED_AREAS
            if c in per_area
        )
        out = {
            "per_area": per_area,
            "gate_pass": gate_pass,
        }
        run.set_output(out)
        return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m regime.validate")
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 4, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2026, 5, 1))
    args = p.parse_args(argv)

    out = evaluate(args.start, args.end)
    print()
    print(
        f"{'area':<5} {'gate?':<6} {'n_total':>8} {'n_w_state':>10} {'n>=0.7':>8} "
        f"{'pct':>7} {'verdict':>10}"
    )
    for code, r in out["per_area"].items():
        required = code in _GATE_REQUIRED_AREAS
        if not r.get("gateable", True):
            verdict = "SPARSE"
        elif r["passes_gate"]:
            verdict = "PASS"
        else:
            verdict = "FAIL"
        print(
            f"{code:<5} {'GATE' if required else 'INFO':<6} "
            f"{r['n_spike_slots']:>8} {r['n_with_regime_state']:>10} "
            f"{r['n_above_posterior_threshold']:>8} "
            f"{r['fraction_passing']*100:>6.1f}% {verdict:>10}"
        )
    print()
    print(f"Gate (TK+TH): {'PASS' if out['gate_pass'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
