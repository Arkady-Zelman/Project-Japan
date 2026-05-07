"""Per-area MRS calibration via statsmodels MarkovRegression.

Per BUILD_SPEC §7.4 + §12 M5. The fit uses 3 regimes with a per-regime
constant trend and per-regime variance — a well-known pragmatic
approximation of the Janczura-Weron 2010 spec (independent spike/drop +
mean-reverting base) that statsmodels supports natively. The "AR=0 in
spike/drop" constraint isn't directly expressible in statsmodels'
MarkovRegression, but with `trend='c'` and `switching_variance=True` the
high-variance, distant-mean regimes naturally fall out as the
spike/drop modes.

Pre-fit transform: log(price_jpy_kwh / (modelled_price_jpy_mwh / 1000)).
The M4 stack output is the deterministic baseline; what's left is the
regime/sentiment process.

Persist: one row per area in `models` (type='mrs') with hyperparams
covering means, variances, transition matrix, and the regime index→label
mapping that `infer_state.py` reads back.

CLI:
    python -m regime.mrs_calibrate            # all 9 areas
    python -m regime.mrs_calibrate --area TK  # single area
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast

import numpy as np
import pandas as pd
import psycopg
from statsmodels.tsa.regime_switching.markov_regression import (  # type: ignore[import-untyped]
    MarkovRegression,
)

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock

from .models import CalibratedModel

logger = logging.getLogger("regime.mrs_calibrate")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# Floor on transformed prices to avoid log(0). Effectively this caps the
# residual range; values outside get clipped before the fit. Tunable.
_PRICE_FLOOR_KWH = 0.01
_RESIDUAL_CLIP = 6.0   # log-residual hard cap (e.g. ¥400/¥1 = log(400) ≈ 6).


@dataclass
class _AreaResiduals:
    area_code: str
    area_id: str
    timestamps: pd.DatetimeIndex
    residuals: np.ndarray   # log(price_kwh / stack_kwh), 1-D


def _load_residuals(
    cur: psycopg.Cursor, area_id: str, area_code: str,
    start: date, end: date,
) -> _AreaResiduals:
    """Pull jepx prices ⨝ stack clearing prices, compute log residual."""
    cur.execute(
        """
        select j.slot_start,
               j.price_jpy_kwh,
               s.modelled_price_jpy_mwh
        from jepx_spot_prices j
        join stack_clearing_prices s
          on s.area_id = j.area_id and s.slot_start = j.slot_start
        where j.area_id = %s
          and j.auction_type = 'day_ahead'
          and j.slot_start >= %s and j.slot_start < %s
          and j.price_jpy_kwh is not null
          and s.modelled_price_jpy_mwh is not null
        order by j.slot_start
        """,
        (
            area_id,
            datetime.combine(start, datetime.min.time(), UTC),
            datetime.combine(end, datetime.min.time(), UTC),
        ),
    )
    rows = cur.fetchall()
    if not rows:
        return _AreaResiduals(area_code, area_id,
                              pd.DatetimeIndex([], tz="UTC"),
                              np.array([], dtype=float))

    df = pd.DataFrame(rows, columns=["slot_start", "price_kwh", "stack_jpy_mwh"])
    df["price_kwh"] = pd.to_numeric(df["price_kwh"], errors="coerce")
    df["stack_kwh"] = pd.to_numeric(df["stack_jpy_mwh"], errors="coerce") / 1000.0
    df = df.dropna(subset=["price_kwh", "stack_kwh"])
    df = df[(df["price_kwh"] > _PRICE_FLOOR_KWH) & (df["stack_kwh"] > _PRICE_FLOOR_KWH)]
    if df.empty:
        return _AreaResiduals(area_code, area_id,
                              pd.DatetimeIndex([], tz="UTC"),
                              np.array([], dtype=float))

    residuals = np.log(df["price_kwh"].to_numpy()) - np.log(df["stack_kwh"].to_numpy())
    residuals = np.clip(residuals, -_RESIDUAL_CLIP, _RESIDUAL_CLIP)
    ts = pd.DatetimeIndex(df["slot_start"]).tz_convert("UTC")
    return _AreaResiduals(area_code, area_id, ts, residuals)


def _fit_mrs(residuals: np.ndarray) -> tuple[dict, np.ndarray]:
    """Fit 3-regime MarkovRegression. Returns (params_dict, smoothed_T_by_3).

    `smoothed` is the T×3 matrix of posterior regime probabilities aligned
    to the input residual order. Caller writes both the params (to `models`)
    and the smoothed probs (to `regime_states`) in one pass — guarantees
    label consistency between the two tables.
    """
    if len(residuals) < 200:
        raise ValueError(f"insufficient residuals for MRS fit: n={len(residuals)}")

    mod = MarkovRegression(
        residuals,
        k_regimes=3,
        trend="c",
        switching_variance=True,
    )
    # `em_iter` does an EM warm-up so the optimizer has a sane starting point.
    # search_reps=20 gives the optimizer 20 different random starts; helps find
    # the heavy-tailed "spike" regime when the residual distribution has thin
    # outliers (TH-style fits otherwise converge to a tight 3-mode fit that
    # misses the extreme-tail mode).
    result = mod.fit(em_iter=30, search_reps=20, disp=False)

    # statsmodels packs params as a 1-D ndarray. Layout for k_regimes=3,
    # trend='c', switching_variance=True is:
    #   params[0..5]   transition probs (6 free params for 3-regime)
    #   params[6..8]   const[0..2] = regime means
    #   params[9..11]  sigma2[0..2] = regime variances
    param_names = list(mod.param_names)
    mean_idxs = [param_names.index(f"const[{k}]") for k in range(3)]
    var_idxs = [param_names.index(f"sigma2[{k}]") for k in range(3)]
    means = np.array([float(result.params[i]) for i in mean_idxs])
    variances = np.array([float(result.params[i]) for i in var_idxs])
    # regime_transition shape (k, k, 1). P[i, j] = P(next=i | prev=j) per
    # statsmodels' convention. We persist as-is + document.
    P = np.asarray(result.regime_transition).squeeze().tolist()

    smoothed = np.asarray(result.smoothed_marginal_probabilities)
    if smoothed.shape[0] == 3 and smoothed.shape[1] == len(residuals):
        smoothed = smoothed.T

    # Regime labeling: in a clean Janczura-Weron 3-regime fit, base is
    # the low-variance "normal trading" regime while spike and drop are
    # heavy-tailed regimes capturing upward and downward jumps. With
    # log(price/stack) residuals and a stack model that's biased high,
    # statsmodels' EM tends to converge to a fit where ONE regime captures
    # both tails (high variance, mean centered near the central tendency)
    # and the other two regimes capture two narrower bands of "normal".
    #
    # Pragmatic labels:
    #   base  = lowest variance regime (mean-reverting trading)
    #   spike = highest variance regime (the catch-all for outliers; in
    #           our fits it absorbs both directions of jump and is the
    #           regime smoothed_probs assigns to extreme price events
    #           like the April 2026 spike slots)
    #   drop  = remaining regime
    var_order = np.argsort(variances)  # ascending
    idx_base = int(var_order[0])
    idx_drop = int(var_order[1])
    idx_spike = int(var_order[2])
    regime_mapping = {
        str(idx_base): "base",
        str(idx_drop): "drop",
        str(idx_spike): "spike",
    }
    params_dict = {
        "means": means.tolist(),
        "variances": variances.tolist(),
        "transition_matrix": P,
        "regime_mapping": regime_mapping,
        "log_likelihood": float(result.llf),
        "aic": float(result.aic),
        "bic": float(result.bic),
        "n_obs": int(len(residuals)),
    }
    return params_dict, smoothed


def _persist(
    cur: psycopg.Cursor,
    cm: CalibratedModel,
) -> str:
    """Insert a new `models` row, mark previous (area, type) ready rows deprecated.

    Returns the new model_id (UUID as string).
    """
    cur.execute(
        """
        update models
        set status = 'deprecated'
        where type = 'mrs' and name = %s and status = 'ready'
        """,
        (cm.name,),
    )
    cur.execute(
        """
        insert into models
          (name, type, version, hyperparams, training_window_start,
           training_window_end, metrics, status)
        values (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s)
        returning id::text
        """,
        (
            cm.name, cm.type, cm.version, json.dumps(cm.hyperparams),
            cm.training_window_start, cm.training_window_end,
            json.dumps(cm.metrics), cm.status,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return cast(str, row[0])


def calibrate_area(
    area_code: str,
    area_id: str,
    *,
    start: date,
    end: date,
    version: str | None = None,
) -> str | None:
    """Fit MRS for one area, persist model + regime_states atomically.

    Writes both the `models` row and the `regime_states` rows for every
    slot in the calibration residual set, in the same transaction. This
    guarantees label consistency — the smoothed probabilities are aligned
    to the same EM convergence as the persisted params.

    Returns the new model_id (or None if skipped).
    """
    if version is None:
        # Include time-of-day so multiple calibrations same-day don't collide.
        version = f"v1-{datetime.now(tz=UTC).strftime('%Y%m%d-%H%M%S')}"

    with compute_run("regime_calibrate") as run:
        run.set_input({
            "area": area_code,
            "version": version,
            "start": start.isoformat(),
            "end": end.isoformat(),
        })

        with connect() as conn:
            with conn.cursor() as cur:
                advisory_lock(cur, f"regime_calibrate_{area_code}")
                resids = _load_residuals(cur, area_id, area_code, start, end)
                if len(resids.residuals) < 200:
                    logger.warning(
                        "%s: only %d residuals, skipping fit", area_code, len(resids.residuals)
                    )
                    run.set_output({
                        "skipped": "insufficient_residuals",
                        "n": int(len(resids.residuals)),
                    })
                    return None

                params, smoothed = _fit_mrs(resids.residuals)
                cm = CalibratedModel(
                    area_code=area_code,
                    name=f"mrs_{area_code}",
                    version=version,
                    hyperparams=params,
                    training_window_start=start,
                    training_window_end=end - timedelta(days=1),
                    metrics={
                        "log_likelihood": params["log_likelihood"],
                        "aic": params["aic"],
                        "bic": params["bic"],
                        "n_obs": params["n_obs"],
                    },
                )
                model_id = _persist(cur, cm)

                # Write regime_states for every residual slot. The mapping
                # in params decodes regime indices to {base, spike, drop}.
                inv = {int(k): v for k, v in params["regime_mapping"].items()}
                idx_base = next(i for i, lbl in inv.items() if lbl == "base")
                idx_spike = next(i for i, lbl in inv.items() if lbl == "spike")
                idx_drop = next(i for i, lbl in inv.items() if lbl == "drop")

                rows: list[tuple] = []
                for ts, probs in zip(resids.timestamps, smoothed, strict=False):
                    p_base = min(max(round(float(probs[idx_base]), 5), 0.0), 1.0)
                    p_spike = min(max(round(float(probs[idx_spike]), 5), 0.0), 1.0)
                    p_drop = min(max(round(float(probs[idx_drop]), 5), 0.0), 1.0)
                    triplet = {"base": p_base, "spike": p_spike, "drop": p_drop}
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
            "%s: fit MRS n=%d means=%s variances=%s mapping=%s rows_written=%d model_id=%s",
            area_code, params["n_obs"],
            [round(m, 3) for m in params["means"]],
            [round(v, 3) for v in params["variances"]],
            params["regime_mapping"],
            inserted,
            model_id,
        )
        run.set_output({
            "model_id": model_id, "rows_written": inserted, **params,
        })
        return model_id


def run_all(start: date, end: date, version: str | None = None) -> dict[str, str | None]:
    """Calibrate every area. Returns {area_code: model_id_or_None}."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select code, id::text from areas where code != 'SYS' order by code")
        areas = list(cur.fetchall())

    out: dict[str, str | None] = {}
    for code, area_id in areas:
        try:
            out[code] = calibrate_area(code, area_id, start=start, end=end, version=version)
        except Exception as e:
            logger.exception("%s: calibration failed", code)
            out[code] = None
            _ = e
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m regime.mrs_calibrate")
    p.add_argument("--area", help="Single-area mode (e.g. TK)")
    p.add_argument("--start", type=date.fromisoformat, default=date(2023, 1, 1))
    p.add_argument("--end", type=date.fromisoformat,
                   help="Exclusive end (default: today + 1 day)")
    p.add_argument("--version")
    args = p.parse_args(argv)

    end = args.end or (date.today() + timedelta(days=1))
    if args.area:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("select id::text from areas where code = %s", (args.area,))
            row = cur.fetchone()
            if not row:
                raise SystemExit(f"unknown area: {args.area}")
            area_id = row[0]
        calibrate_area(args.area, area_id, start=args.start, end=end, version=args.version)
    else:
        out = run_all(args.start, end, args.version)
        logger.info("run_all: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
