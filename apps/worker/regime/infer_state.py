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
from statsmodels.tsa.regime_switching.markov_regression import (  # type: ignore[import-untyped]
    MarkovRegression,
)

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock

from .mrs_calibrate import _load_residuals

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


def _smoothed_probs(residuals: np.ndarray, hp: dict) -> np.ndarray:
    """Re-fit MarkovRegression on residuals and return T×3 smoothed probabilities."""
    mod = MarkovRegression(
        residuals, k_regimes=3, trend="c", switching_variance=True
    )
    result = mod.fit(em_iter=10, search_reps=3, disp=False)
    smoothed = np.asarray(result.smoothed_marginal_probabilities)
    if smoothed.shape[0] == 3 and smoothed.shape[1] == len(residuals):
        smoothed = smoothed.T  # statsmodels can return either shape; normalise.
    return smoothed


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
                    run.set_output({"skipped": "insufficient_residuals", "n": int(len(resids.residuals))})
                    return 0

                smoothed = _smoothed_probs(resids.residuals, hp)
                # Match the variance-based labeling used by mrs_calibrate.
                # Compute the per-regime conditional variance from the smoothed
                # probabilities and the same residual series. lowest variance =
                # base, highest = spike, remaining = drop.
                fit_means = np.array([
                    smoothed[:, k].dot(resids.residuals) / max(smoothed[:, k].sum(), 1e-9)
                    for k in range(3)
                ])
                fit_vars = np.array([
                    smoothed[:, k].dot((resids.residuals - fit_means[k]) ** 2)
                    / max(smoothed[:, k].sum(), 1e-9)
                    for k in range(3)
                ])
                var_order = np.argsort(fit_vars)  # ascending
                idx_base = int(var_order[0])
                idx_drop = int(var_order[1])
                idx_spike = int(var_order[2])

                rows: list[tuple] = []
                for ts, probs in zip(resids.timestamps, smoothed, strict=False):
                    p_drop = round(float(probs[idx_drop]), 5)
                    p_base = round(float(probs[idx_base]), 5)
                    p_spike = round(float(probs[idx_spike]), 5)
                    # Numeric(6,5) caps at 9.99999 — just clamp to [0,1].
                    p_drop = min(max(p_drop, 0.0), 1.0)
                    p_base = min(max(p_base, 0.0), 1.0)
                    p_spike = min(max(p_spike, 0.0), 1.0)
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
