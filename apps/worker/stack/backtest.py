"""RMSE/MAE/MAPE harness for the stack model vs realised JEPX clearing prices.

The M4 STOP gate is RMSE < ¥3/kWh on routine slots (BUILD_SPEC §12 M4).
"Routine" = drop the top 1 % of slots by realised price per area, treating
those as spike events the fundamental model isn't expected to fit.

CLI:
    python -m stack.backtest --start 2023-01-01 --end 2024-04-01 [--area TK]

Outputs a per-area RMSE/MAE/MAPE table. Logs the result to compute_runs
(kind='stack_backtest') so it's visible in the dashboard.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

import numpy as np

from common.audit import compute_run
from common.db import connect

logger = logging.getLogger("stack.backtest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# Spike threshold: drop slots where realised price > this percentile.
# "Routine slots" per spec.
_ROUTINE_PERCENTILE = 0.99


@dataclass
class _AreaResult:
    area_code: str
    n_slots: int
    n_routine: int
    rmse_jpy_kwh: float
    mae_jpy_kwh: float
    mape_pct: float
    realised_mean_jpy_kwh: float
    modelled_mean_jpy_kwh: float


def _run_one_area(
    cur,
    area_id: str,
    area_code: str,
    start: date,
    end: date,
) -> _AreaResult | None:
    cur.execute(
        """
        select s.modelled_price_jpy_mwh, j.price_jpy_kwh
        from stack_clearing_prices s
        join jepx_spot_prices j
          on j.area_id = s.area_id
         and j.slot_start = s.slot_start
         and j.auction_type = 'day_ahead'
        where s.area_id = %s
          and s.slot_start >= %s and s.slot_start < %s
          and s.modelled_price_jpy_mwh is not null
          and j.price_jpy_kwh is not null
        """,
        (
            area_id,
            datetime.combine(start, datetime.min.time(), UTC),
            datetime.combine(end, datetime.min.time(), UTC),
        ),
    )
    rows = cur.fetchall()
    if not rows:
        logger.warning("no overlapping rows for area=%s in window", area_code)
        return None

    arr = np.array(
        [(float(m) / 1000.0, float(r)) for m, r in rows],
        dtype=float,
    )
    modelled = arr[:, 0]
    realised = arr[:, 1]

    threshold = float(np.quantile(realised, _ROUTINE_PERCENTILE))
    mask = realised <= threshold
    m_routine = modelled[mask]
    r_routine = realised[mask]

    err = r_routine - m_routine
    rmse = float(np.sqrt((err**2).mean())) if len(err) else float("nan")
    mae = float(np.abs(err).mean()) if len(err) else float("nan")
    nonzero = r_routine != 0
    mape = (
        float(np.abs(err[nonzero] / r_routine[nonzero]).mean() * 100.0)
        if nonzero.any() else float("nan")
    )

    return _AreaResult(
        area_code=area_code,
        n_slots=len(rows),
        n_routine=int(mask.sum()),
        rmse_jpy_kwh=rmse,
        mae_jpy_kwh=mae,
        mape_pct=mape,
        realised_mean_jpy_kwh=float(realised.mean()),
        modelled_mean_jpy_kwh=float(modelled.mean()),
    )


def run_backtest(start: date, end: date, areas: list[str] | None = None) -> dict:
    """Compute per-area metrics. Returns dict suitable for compute_runs.output."""
    with compute_run("stack_backtest") as run:
        run.set_input({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "areas": areas,
            "routine_percentile": _ROUTINE_PERCENTILE,
        })

        results: dict[str, dict] = {}
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select id::text, code from areas where code != 'SYS'")
                area_rows = [(aid, code) for aid, code in cur.fetchall()]

                target = [
                    (aid, code) for aid, code in area_rows
                    if not areas or code in areas
                ]
                for area_id, area_code in target:
                    r = _run_one_area(cur, area_id, area_code, start, end)
                    if r is not None:
                        results[area_code] = asdict(r)

        gate = {
            "threshold_jpy_kwh": 3.0,
            "areas_passing": [
                code for code, r in results.items() if r["rmse_jpy_kwh"] < 3.0
            ],
            "areas_failing": [
                code for code, r in results.items() if r["rmse_jpy_kwh"] >= 3.0
            ],
        }
        out = {"per_area": results, "gate": gate}
        run.set_output(out)
        return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stack.backtest")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--area", help="Limit to one area code (e.g. TK)")
    args = parser.parse_args(argv)

    areas = [args.area] if args.area else None
    out = run_backtest(args.start, args.end, areas)

    print()
    print(
        f"{'area':<6} {'n_total':>8} {'n_routine':>10} "
        f"{'RMSE ¥/kWh':>12} {'MAE':>8} {'MAPE%':>8} "
        f"{'realised':>10} {'modelled':>10} {'gate':>6}"
    )
    for code, r in out["per_area"].items():
        gate = "PASS" if r["rmse_jpy_kwh"] < 3.0 else "FAIL"
        print(
            f"{code:<6} {r['n_slots']:>8} {r['n_routine']:>10} "
            f"{r['rmse_jpy_kwh']:>12.3f} {r['mae_jpy_kwh']:>8.3f} "
            f"{r['mape_pct']:>8.1f} "
            f"{r['realised_mean_jpy_kwh']:>10.3f} "
            f"{r['modelled_mean_jpy_kwh']:>10.3f} "
            f"{gate:>6}"
        )
    print()
    print(f"Gate: {out['gate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
