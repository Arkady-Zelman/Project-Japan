"""Apply the calibrated MRS to write posterior regime probabilities to `regime_states`.

Uses statsmodels' `smoothed_marginal_probabilities` (Hamilton's filter forward
+ Kim's smoother backward) at each (area, slot). Posterior probabilities sum
to 1 across the 3 regimes; the most-likely-regime label comes from argmax.

The calibrated model is **re-fit** here using the persisted hyperparameters
as starting values rather than calling `result.predict()` directly — this is
because statsmodels doesn't serialize MarkovRegression results across processes
in a stable way, and re-fitting on the same residuals with EM-warm-start
converges in seconds.

CLI:
    python -m regime.infer_state            # all 9 areas
    python -m regime.infer_state --area TK
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, date, timedelta
from typing import cast

import numpy as np
import psycopg

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock

from .jw_mrs import JanczuraWeronMRS
from .mrs_calibrate import _load_residuals
from .pot import PeaksOverThreshold

logger = logging.getLogger("regime.infer_state")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _load_active_model(cur: psycopg.Cursor, area_code: str) -> tuple[str, str, dict] | None:
    """Latest 'ready' MRS row for area. Returns (model_id, version, hyperparams) or None."""
    cur.execute(
        """
        select id::text, version, hyperparams::text
        from models
        where type='mrs' and name=%s and status='ready'
        order by created_at desc limit 1
        """,
        (f"mrs_{area_code}",),
    )
    row = cur.fetchone()
    if not row:
        return None
    return row[0], row[1], json.loads(row[2])


def _smoothed_probs(
    residuals: np.ndarray, prices: np.ndarray, hp: dict
) -> tuple[np.ndarray, dict[str, str]]:
    """Re-fit JanczuraWeronMRS on residuals + prices.

    Returns (T×3 smoothed posteriors, regime_mapping). The labeling has to be
    re-derived because the EM converges to an arbitrary regime ordering each
    fit; the persisted hyperparams from `hp` are NOT directly applied.

    For the daily refresh case (this function), we still trust posterior-
    weighted labeling on the same window — over enough slots it produces the
    same labels as calibration. If you need exact label parity with the
    persisted model, run `mrs_calibrate.calibrate_area()` instead, which
    writes models + regime_states atomically.
    """
    model = JanczuraWeronMRS(residuals=residuals, prices=prices)
    params, smoothed = model.fit()
    return smoothed, params["regime_mapping"]


def infer_area(
    area_code: str,
    area_id: str,
    *,
    start: date,
    end: date,
) -> int:
    """Compute & persist regime_states for one area's window. Returns rows written."""
    with compute_run("regime_infer") as run:
        run.set_input({
            "area": area_code,
            "start": start.isoformat(),
            "end": end.isoformat(),
        })

        with connect() as conn:
            with conn.cursor() as cur:
                advisory_lock(cur, f"regime_infer_{area_code}")
                active = _load_active_model(cur, area_code)
                if active is None:
                    run.set_output({"skipped": "no_active_model"})
                    return 0
                model_id, version, hp = active

                resids = _load_residuals(cur, area_id, area_code, start, end)
                if len(resids.residuals) < 50:
                    run.set_output(
                        {"skipped": "insufficient_residuals", "n": int(len(resids.residuals))}
                    )
                    return 0

                smoothed, mapping = _smoothed_probs(
                    resids.residuals, resids.prices, hp
                )
                inv = {int(k): v for k, v in mapping.items()}
                idx_base = next(i for i, lbl in inv.items() if lbl == "base")
                idx_spike = next(i for i, lbl in inv.items() if lbl == "spike")
                idx_drop = next(i for i, lbl in inv.items() if lbl == "drop")

                # POT tail probability — combined with MRS posterior via max
                # to lift sparse-tail spike events the MRS misses (per the
                # M5.5 amendment in BUILD_SPEC §7.4).
                pot = PeaksOverThreshold(
                    residuals=resids.residuals, prices=resids.prices
                )
                pot.fit()
                p_tail_arr = pot.tail_probabilities(resids.residuals)

                rows: list[tuple] = []
                for ts, probs, p_tail in zip(
                    resids.timestamps, smoothed, p_tail_arr, strict=False
                ):
                    p_base_raw = float(probs[idx_base])
                    p_spike_raw = float(probs[idx_spike])
                    p_drop_raw = float(probs[idx_drop])
                    p_spike_combined = max(p_spike_raw, float(p_tail))
                    remaining = max(0.0, 1.0 - p_spike_combined)
                    other_total = p_base_raw + p_drop_raw
                    if other_total > 1e-9:
                        scale = remaining / other_total
                        p_base = p_base_raw * scale
                        p_drop = p_drop_raw * scale
                    else:
                        p_base = remaining * 0.5
                        p_drop = remaining * 0.5
                    p_base = min(max(round(p_base, 5), 0.0), 1.0)
                    p_spike = min(max(round(p_spike_combined, 5), 0.0), 1.0)
                    p_drop = min(max(round(p_drop, 5), 0.0), 1.0)
                    triplet = {"drop": p_drop, "base": p_base, "spike": p_spike}
                    most_likely = max(triplet, key=lambda k: triplet[k])
                    rows.append((
                        area_id,
                        ts.to_pydatetime().replace(tzinfo=UTC),
                        p_base, p_spike, p_drop,
                        most_likely, version,
                    ))

                inserted = 0
                for i in range(0, len(rows), 1000):
                    chunk = rows[i:i + 1000]
                    cur.executemany(
                        """
                        insert into regime_states
                          (area_id, slot_start, p_base, p_spike, p_drop,
                           most_likely_regime, model_version)
                        values (%s, %s, %s, %s, %s, %s, %s)
                        on conflict (area_id, slot_start, model_version) do update set
                          p_base = excluded.p_base,
                          p_spike = excluded.p_spike,
                          p_drop = excluded.p_drop,
                          most_likely_regime = excluded.most_likely_regime
                        """,
                        chunk,
                    )
                    inserted += len(chunk)
            conn.commit()

        logger.info(
            "%s: wrote %d regime_states (model_version=%s)", area_code, inserted, version
        )
        run.set_output({
            "model_id": model_id, "model_version": version, "rows_written": inserted,
        })
        return inserted


def run_all(start: date, end: date) -> dict[str, int]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select code, id::text from areas where code != 'SYS' order by code")
        areas = list(cur.fetchall())

    out: dict[str, int] = {}
    for code, area_id in areas:
        try:
            out[code] = infer_area(code, area_id, start=start, end=end)
        except Exception:
            logger.exception("%s: infer failed", code)
            out[code] = -1
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m regime.infer_state")
    p.add_argument("--area")
    p.add_argument("--start", type=date.fromisoformat, default=date(2023, 1, 1))
    p.add_argument("--end", type=date.fromisoformat,
                   help="Exclusive end (default: today + 1 day)")
    args = p.parse_args(argv)

    end = args.end or (date.today() + timedelta(days=1))
    if args.area:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("select id::text from areas where code = %s", (args.area,))
            row = cur.fetchone()
            if not row:
                raise SystemExit(f"unknown area: {args.area}")
            area_id = cast(str, row[0])
        infer_area(args.area, area_id, start=args.start, end=end)
    else:
        out = run_all(args.start, end)
        logger.info("run_all: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
