"""Production LSM valuation runner — operator-triggered via Modal HTTP endpoint.

Flow (mirrors `regime/mrs_calibrate.py::calibrate_area`):

1. Acquire `advisory_lock(cur, f"lsm_{valuation_id}")` so concurrent retries
   on the same valuation_id race-fail safely.
2. SELECT the queued `valuations` row → asset_id, forecast_run_id, horizon.
3. SELECT the asset spec from `assets`.
4. Bulk-fetch `forecast_paths` for that run → reshape to (n_paths, T+1).
5. UPDATE valuations to status='running'.
6. Run `engine.run_lsm(...)`.
7. Bulk-INSERT `valuation_decisions` rows (one per action slot).
8. UPDATE `valuations` to status='done' with all numeric outputs.
9. On any exception: UPDATE to status='failed' with `error` text.

Wraps in `compute_run("lsm_valuation")` so the dashboard sees it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from uuid import UUID

import numpy as np
import psycopg

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock

from .engine import run_lsm
from .models import AssetSpec, ValuationResult

logger = logging.getLogger("lsm.runner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# JEPX day-ahead is half-hourly.
SLOT_MINUTES = 30
DEFAULT_HORIZON_SLOTS = 48


def _load_queued_valuation(cur: psycopg.Cursor, valuation_id: UUID) -> dict:
    cur.execute(
        """
        select id::text, asset_id::text, forecast_run_id::text,
               horizon_start, horizon_end, basis_functions::text, n_paths,
               n_volume_grid, status
        from valuations where id = %s
        """,
        (str(valuation_id),),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"valuation {valuation_id} not found")
    return {
        "id": row[0], "asset_id": row[1], "forecast_run_id": row[2],
        "horizon_start": row[3], "horizon_end": row[4],
        "basis": (json.loads(row[5]) if row[5] else {}).get("basis", "power"),
        "n_paths": row[6], "n_volume_grid": row[7] or 101,
        "status": row[8],
    }


def _load_asset(cur: psycopg.Cursor, asset_id: str) -> AssetSpec:
    cur.execute(
        """
        select name, asset_type, power_mw, energy_mwh, round_trip_eff,
               max_cycles_per_year, degradation_jpy_mwh,
               soc_min_pct, soc_max_pct
        from assets where id = %s
        """,
        (asset_id,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"asset {asset_id} not found")
    name, asset_type, power_mw, energy_mwh, eff, cycles, deg, soc_min, soc_max = row
    energy = float(energy_mwh)
    return AssetSpec(
        name=name,
        asset_type=asset_type,
        energy_mwh=energy,
        soc_min_mwh=energy * float(soc_min),
        soc_max_mwh=energy * float(soc_max),
        soc_initial_mwh=energy * (float(soc_min) + float(soc_max)) / 2.0,
        power_mw_charge=float(power_mw),
        power_mw_discharge=float(power_mw),
        round_trip_eff=float(eff),
        degradation_jpy_mwh=float(deg or 0.0),
        max_cycles_per_year=float(cycles or 10_000.0),
    )


def _load_forecast_paths(
    cur: psycopg.Cursor, forecast_run_id: str,
) -> tuple[np.ndarray, list[datetime]]:
    """Returns (paths array shape (n_paths, n_slots+1), slot_starts list).

    The path array's column 0 is the forecast origin (a "current price" anchor)
    and columns 1..T are the forecast slots. We pick the first observed slot
    as both the t=0 anchor and the start of the horizon — the engine uses
    column 0 for its first decision.
    """
    cur.execute(
        """
        select horizon_slots, n_paths, forecast_origin
        from forecast_runs where id = %s
        """,
        (forecast_run_id,),
    )
    run = cur.fetchone()
    if not run:
        raise RuntimeError(f"forecast_run {forecast_run_id} not found")
    horizon_slots, n_paths = int(run[0]), int(run[1])

    cur.execute(
        """
        select path_id, slot_start, price_jpy_kwh
        from forecast_paths
        where forecast_run_id = %s
        order by slot_start, path_id
        """,
        (forecast_run_id,),
    )
    rows = cur.fetchall()
    expected = horizon_slots * n_paths
    if len(rows) != expected:
        raise RuntimeError(
            "incomplete forecast_paths for run "
            f"{forecast_run_id}: found {len(rows)} rows, expected {expected} "
            f"({horizon_slots} horizon slots x {n_paths} paths)"
        )

    # Build (n_paths, horizon_slots) price matrix in JPY/MWh.
    slot_set: dict[datetime, int] = {}
    paths_kwh = np.zeros((n_paths, horizon_slots), dtype=np.float64)
    seen = np.zeros((n_paths, horizon_slots), dtype=np.bool_)
    for path_id, slot_start, price_kwh in rows:
        path_idx = int(path_id)
        if path_idx < 0 or path_idx >= n_paths:
            raise RuntimeError(
                f"forecast_paths path_id {path_idx} outside expected range 0..{n_paths - 1}"
            )
        if slot_start not in slot_set:
            if len(slot_set) >= horizon_slots:
                raise RuntimeError(
                    "forecast_paths contains more distinct slots than "
                    f"forecast_runs.horizon_slots={horizon_slots}"
                )
            slot_set[slot_start] = len(slot_set)
        t_idx = slot_set[slot_start]
        if seen[path_idx, t_idx]:
            raise RuntimeError(
                f"duplicate forecast_paths cell for path_id={path_idx}, slot_start={slot_start}"
            )
        if price_kwh is None:
            raise RuntimeError(
                f"forecast_paths has null price for path_id={path_idx}, slot_start={slot_start}"
            )
        paths_kwh[path_idx, t_idx] = float(price_kwh)
        seen[path_idx, t_idx] = True
    slot_starts = sorted(slot_set.keys())
    if len(slot_starts) != horizon_slots:
        raise RuntimeError(
            "forecast_paths slot count mismatch for run "
            f"{forecast_run_id}: found {len(slot_starts)} distinct slots, "
            f"expected {horizon_slots}"
        )
    missing = int(seen.size - seen.sum())
    if missing:
        examples = np.argwhere(~seen)[:5].tolist()
        raise RuntimeError(
            "forecast_paths is missing "
            f"{missing} path-slot cells for run {forecast_run_id}; examples={examples}"
        )

    # Engine wants prices in JPY/MWh (so cash flows are in JPY when multiplied
    # by MWh of action). forecast_paths stores JPY/kWh — multiply by 1000.
    paths_mwh = paths_kwh * 1000.0

    # Engine expects (M, T+1) where T+1 = n_decisions + 1. We have T slot prices
    # and want T-1 decisions ending at the last slot. Use the first slot as the
    # anchor and slots 1..T as the horizon → T-1 decision steps. This is the
    # standard "current price + future paths" framing.
    return paths_mwh, slot_starts


def run_valuation(valuation_id: UUID) -> ValuationResult:
    """End-to-end. Persists all rows. Updates status. Audits via compute_runs."""
    with compute_run("lsm_valuation") as run:
        run.set_input({"valuation_id": str(valuation_id)})

        with connect() as conn, conn.cursor() as cur:
            advisory_lock(cur, f"lsm_{valuation_id}")
            v = _load_queued_valuation(cur, valuation_id)
            if v["status"] != "queued":
                logger.warning("valuation %s already in status=%s", valuation_id, v["status"])

            asset = _load_asset(cur, v["asset_id"])
            paths_mwh, slot_starts = _load_forecast_paths(cur, v["forecast_run_id"])
            n_paths, n_slots = paths_mwh.shape

            # Mark running before the heavy compute starts.
            cur.execute(
                "update valuations set status='running' where id = %s",
                (str(valuation_id),),
            )
            conn.commit()

        # Heavy compute outside the transaction so other queries can run.
        result = run_lsm(
            paths=paths_mwh,
            asset=asset,
            n_volume_grid=v["n_volume_grid"],
            basis=v["basis"],
            dt_days=SLOT_MINUTES / (60.0 * 24.0),   # half-hour slots → days
            discount_rate=0.0,
        )

        # Persist results in one transaction.
        with connect() as conn, conn.cursor() as cur:
            advisory_lock(cur, f"lsm_persist_{valuation_id}")
            T = n_slots - 1
            decision_rows: list[tuple] = []
            for t in range(T):
                # action_mw is the realised action rate; soc_mwh is the
                # post-action SoC at slot_start[t+1].
                soc = result.slot_mean_soc_mwh[t + 1]
                act = result.slot_mean_action_mw[t]
                pnl = result.slot_expected_pnl_jpy[t]
                slot = slot_starts[t]
                decision_rows.append((
                    str(valuation_id), slot, soc, act, pnl,
                ))
            for i in range(0, len(decision_rows), 1000):
                chunk = decision_rows[i:i + 1000]
                cur.executemany(
                    """
                    insert into valuation_decisions
                      (valuation_id, slot_start, soc_mwh, action_mw, expected_pnl_jpy)
                    values (%s, %s, %s, %s, %s)
                    on conflict (valuation_id, slot_start) do update set
                      soc_mwh = excluded.soc_mwh,
                      action_mw = excluded.action_mw,
                      expected_pnl_jpy = excluded.expected_pnl_jpy
                    """,
                    chunk,
                )

            cur.execute(
                """
                update valuations set
                  status = 'done',
                  total_value_jpy = %s,
                  intrinsic_value_jpy = %s,
                  extrinsic_value_jpy = %s,
                  ci_lower_jpy = %s,
                  ci_upper_jpy = %s,
                  n_paths = %s,
                  n_volume_grid = %s,
                  runtime_seconds = %s,
                  completed_at = now()
                where id = %s
                """,
                (
                    result.total_jpy, result.intrinsic_jpy, result.extrinsic_jpy,
                    result.ci_lower_jpy, result.ci_upper_jpy,
                    result.n_paths, result.n_volume_grid, result.runtime_seconds,
                    str(valuation_id),
                ),
            )
            conn.commit()

        run.set_output({
            "valuation_id": str(valuation_id),
            "total_jpy": result.total_jpy,
            "intrinsic_jpy": result.intrinsic_jpy,
            "extrinsic_jpy": result.extrinsic_jpy,
            "runtime_seconds": result.runtime_seconds,
            "n_decisions": T,
        })
        logger.info(
            "valuation %s done: total=%.0f intrinsic=%.0f extrinsic=%.0f in %.2fs",
            valuation_id, result.total_jpy, result.intrinsic_jpy,
            result.extrinsic_jpy, result.runtime_seconds,
        )
        return result


def mark_failed(valuation_id: UUID, error_text: str) -> None:
    """Idempotent failure mark — called from the Modal endpoint's error handler."""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update valuations set
                  status = 'failed',
                  error = %s,
                  completed_at = now()
                where id = %s
                """,
                (error_text[:2000], str(valuation_id)),
            )
            conn.commit()
    except Exception:
        logger.exception("failed to mark valuation %s failed", valuation_id)
