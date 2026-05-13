"""Daily demo refresh for the public /workbench + /lab pages.

Idempotent: every cron firing produces a fresh LSM valuation and a fresh
4-strategy backtest tagged is_demo=true. Old demo rows stay in the DB; the
read-side endpoints pick the most recent.

Tied to the schema added by `supabase/migrations/006_demo_examples.sql`:
demo rows have `user_id = null` and `is_demo = true`, bypassing the
`auth.users` FK that real-user rows obey.

Wraps each step in its own `compute_run("demo_*")` so cron health surfaces
demo failures separately from production paths.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from common.audit import compute_run
from common.db import connect

logger = logging.getLogger("demo.run_daily")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

DEMO_ASSET_NAME = "Demo: 100 MWh / 50 MW BESS (Tokyo)"
DEMO_AREA_CODE = "TK"
BACKTEST_LOOKBACK_DAYS = 30


def ensure_demo_asset() -> UUID:
    """Upsert the single demo asset, return its id.

    Schema guarantees exactly one row with is_demo=true (unique partial
    index). If the demo asset exists, reuse it; otherwise insert.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select id from assets where is_demo = true limit 1")
        row = cur.fetchone()
        if row:
            return UUID(str(row[0]))

        cur.execute(
            "select id from areas where code = %s",
            (DEMO_AREA_CODE,),
        )
        area = cur.fetchone()
        if not area:
            raise RuntimeError(f"area {DEMO_AREA_CODE} not found")
        area_id = area[0]

        cur.execute(
            """
            insert into assets (
              portfolio_id, user_id, name, asset_type, area_id,
              power_mw, energy_mwh, round_trip_eff,
              soc_min_pct, soc_max_pct,
              max_cycles_per_year, degradation_jpy_mwh,
              is_demo
            )
            values (null, null, %s, 'bess_li_ion', %s,
                    50.0, 100.0, 0.85,
                    0.10, 0.90,
                    365.0, 0.0,
                    true)
            returning id
            """,
            (DEMO_ASSET_NAME, area_id),
        )
        new_row = cur.fetchone()
        if not new_row:
            raise RuntimeError("failed to insert demo asset")
        conn.commit()
        return UUID(str(new_row[0]))


def queue_demo_valuation(asset_id: UUID) -> UUID:
    """Queue a `valuations` row pointing at the latest TK forecast_run.

    The Modal LSM endpoint (or the local runner) will pick this up.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select fr.id, fr.forecast_origin, fr.horizon_slots
            from forecast_runs fr
            join areas a on a.id = fr.area_id
            where a.code = %s
            order by fr.forecast_origin desc
            limit 1
            """,
            (DEMO_AREA_CODE,),
        )
        run = cur.fetchone()
        if not run:
            raise RuntimeError(
                f"no forecast_run for {DEMO_AREA_CODE} — demo LSM cannot proceed"
            )
        run_id, origin, horizon_slots = run
        horizon_end = origin + timedelta(minutes=30 * int(horizon_slots))

        cur.execute(
            """
            insert into valuations (
              asset_id, user_id, forecast_run_id, method, status,
              horizon_start, horizon_end, n_paths, n_volume_grid,
              is_demo
            )
            values (%s, null, %s, 'lsm', 'queued', %s, %s, 1000, 51, true)
            returning id
            """,
            (str(asset_id), str(run_id), origin, horizon_end),
        )
        new_row = cur.fetchone()
        if not new_row:
            raise RuntimeError("failed to queue demo valuation")
        conn.commit()
        return UUID(str(new_row[0]))


def queue_demo_backtests(asset_id: UUID) -> list[UUID]:
    """Queue one `backtests` row per strategy across the last N days."""
    today = datetime.now(tz=UTC).date()
    window_end = today
    window_start = window_end - timedelta(days=BACKTEST_LOOKBACK_DAYS)
    strategies = ["naive_spread", "intrinsic", "rolling_intrinsic", "lsm"]
    out: list[UUID] = []
    with connect() as conn, conn.cursor() as cur:
        for strat in strategies:
            cur.execute(
                """
                insert into backtests (
                  asset_id, user_id, strategy, window_start, window_end,
                  status, is_demo
                )
                values (%s, null, %s, %s, %s, 'queued', true)
                returning id
                """,
                (str(asset_id), strat, window_start, window_end),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"failed to queue demo backtest for {strat}")
            out.append(UUID(str(row[0])))
        conn.commit()
    return out


def run() -> dict:
    """Top-level demo refresh: seed asset, run LSM, run 4 backtests.

    Each step wraps in its own compute_run so cron-health shows three
    distinct dots (demo_asset, demo_lsm, demo_backtest). A failure in one
    step doesn't block subsequent steps.
    """
    out: dict = {}

    with compute_run("demo_asset") as run_ctx:
        try:
            asset_id = ensure_demo_asset()
            run_ctx.set_output({"asset_id": str(asset_id)})
            out["demo_asset"] = {"asset_id": str(asset_id)}
        except Exception as e:  # noqa: BLE001
            out["demo_asset"] = {"error": str(e)}
            return out

    # ---- LSM valuation ----
    from lsm.runner import (
        mark_failed as lsm_mark_failed,
    )
    from lsm.runner import (
        run_valuation,
    )
    try:
        valuation_id = queue_demo_valuation(asset_id)
        try:
            result = run_valuation(valuation_id)
            out["demo_lsm"] = {
                "valuation_id": str(valuation_id),
                "total_jpy": float(result.total_jpy),
            }
        except Exception as e:  # noqa: BLE001
            lsm_mark_failed(valuation_id, repr(e))
            out["demo_lsm"] = {"valuation_id": str(valuation_id), "error": str(e)}
    except Exception as e:  # noqa: BLE001
        # Couldn't even queue (no forecast available)
        out["demo_lsm"] = {"error": str(e)}

    # ---- Backtests (one row per strategy) ----
    from backtest.runner import (
        mark_failed as bt_mark_failed,
    )
    from backtest.runner import (
        run_backtest,
    )
    try:
        backtest_ids = queue_demo_backtests(asset_id)
        bt_results: list[dict] = []
        for bid in backtest_ids:
            try:
                res = run_backtest(bid, spread_jpy_kwh=2.0)
                bt_results.append({
                    "backtest_id": str(bid),
                    "strategy": res.strategy,
                    "realised_pnl_jpy": float(res.realised_pnl_jpy or 0.0),
                })
            except Exception as e:  # noqa: BLE001
                bt_mark_failed(bid, repr(e))
                bt_results.append({"backtest_id": str(bid), "error": str(e)})
        out["demo_backtest"] = bt_results
    except Exception as e:  # noqa: BLE001
        out["demo_backtest"] = {"error": str(e)}

    return out
