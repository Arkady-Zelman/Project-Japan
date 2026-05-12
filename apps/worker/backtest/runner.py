"""Production backtest runner — operator-triggered via Modal HTTP endpoint.

Mirrors the lsm/runner.py pattern: load queued backtests row, fetch
realised prices + stack model output for the window, dispatch the chosen
strategy, apply slippage, compute Sharpe + max drawdown, persist all
metrics + per-slot trade rows back into the row.
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import date, datetime
from typing import cast
from uuid import UUID

import numpy as np
import psycopg

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock
from lsm.models import AssetSpec

from .models import BacktestResult, StrategyName
from .slippage import linear_bid_ask
from .strategies import HOURS_PER_SLOT, KWH_PER_MWH, get_strategy

logger = logging.getLogger("backtest.runner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _load_backtest_row(cur: psycopg.Cursor, backtest_id: UUID) -> dict:
    cur.execute(
        """
        select id::text, asset_id::text, strategy, window_start, window_end, status
        from backtests where id = %s
        """,
        (str(backtest_id),),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"backtest {backtest_id} not found")
    return {
        "id": row[0], "asset_id": row[1], "strategy": row[2],
        "window_start": row[3], "window_end": row[4], "status": row[5],
    }


def _load_asset_spec(cur: psycopg.Cursor, asset_id: str) -> AssetSpec:
    cur.execute(
        """
        select name, asset_type, power_mw, energy_mwh, round_trip_eff,
               max_cycles_per_year, degradation_jpy_mwh, soc_min_pct, soc_max_pct
        from assets where id = %s
        """,
        (asset_id,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"asset {asset_id} not found")
    name, atype, power_mw, energy_mwh, eff, cycles, deg, soc_min, soc_max = row
    energy = float(energy_mwh)
    return AssetSpec(
        name=name, asset_type=atype,
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


def _load_window_prices(
    cur: psycopg.Cursor, area_id: str, start: date, end: date,
) -> tuple[np.ndarray, np.ndarray, list[datetime]]:
    """Returns (realised_jpy_kwh, stack_jpy_kwh, slot_starts) aligned by slot.

    Stack array has NaN for slots where the M4 stack model has no row;
    LSMStackStrategy will fall back to mid in those slots.
    """
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.min.time())
    # Realised JEPX prices first.
    cur.execute(
        """
        select slot_start, price_jpy_kwh from jepx_spot_prices
        where area_id = %s and auction_type = 'day_ahead'
          and slot_start >= %s and slot_start < %s
          and price_jpy_kwh is not null
        order by slot_start
        """,
        (area_id, start_dt, end_dt),
    )
    rows = cur.fetchall()
    slot_starts = [r[0] for r in rows]
    realised = np.array([float(r[1]) for r in rows], dtype=np.float64)
    # Stack (modelled_price_jpy_mwh → /kWh). Build a dict indexed by ts.
    cur.execute(
        """
        select slot_start, modelled_price_jpy_mwh from stack_clearing_prices
        where area_id = %s and slot_start >= %s and slot_start < %s
          and modelled_price_jpy_mwh is not null
        """,
        (area_id, start_dt, end_dt),
    )
    stack_lookup = {r[0]: float(r[1]) / 1000.0 for r in cur.fetchall()}
    stack = np.array(
        [stack_lookup.get(ts, np.nan) for ts in slot_starts], dtype=np.float64,
    )
    # For slots with NaN stack, fall back to the realised mid so LSMStack
    # sees a sane forecast (degenerate to "today's price will continue").
    nan_mask = np.isnan(stack)
    stack = np.where(nan_mask, realised, stack)
    return realised, stack, slot_starts


def _load_asset_area(cur: psycopg.Cursor, asset_id: str) -> str:
    cur.execute("select area_id::text from assets where id = %s", (asset_id,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"asset {asset_id} not found")
    return cast(str, row[0])


def _compute_sharpe(realised_cash: np.ndarray, slot_minutes: int = 30) -> float:
    """Annualised Sharpe of half-hourly cash flows.

    Aggregate to daily returns first (sum within each calendar day) then
    Sharpe on those. Annualisation factor = sqrt(365). If stdev is
    zero or there's <2 days, return 0.
    """
    slots_per_day = int(round(24 * 60 / slot_minutes))
    n = realised_cash.shape[0]
    n_days = n // slots_per_day
    if n_days < 2:
        return 0.0
    daily = realised_cash[: n_days * slots_per_day].reshape(n_days, slots_per_day).sum(axis=1)
    mu = float(daily.mean())
    sd = float(daily.std(ddof=1))
    if sd <= 0:
        return 0.0
    return mu / sd * math.sqrt(365)


def _compute_max_drawdown(realised_cash: np.ndarray) -> float:
    """Peak-to-trough drawdown on the cumulative-cash equity curve, in JPY.

    Returns the maximum *positive* drop from a running max (i.e., the
    worst peak-to-trough loss). Returns 0 if the curve is monotone-up.
    """
    cum = np.cumsum(realised_cash)
    if cum.size == 0:
        return 0.0
    running_max = np.maximum.accumulate(cum)
    dd = running_max - cum   # positive when underwater
    return float(dd.max())


def _build_trade_rows(
    slot_starts: list[datetime],
    soc: np.ndarray,
    actions: np.ndarray,
    mid_kwh: np.ndarray,
    realised_cash: np.ndarray,
) -> list[dict]:
    """Compact list of per-slot dicts for `trades_jsonb`. Sub-sampled to keep
    the JSON small — keep every slot for ≤ 1 month, every 4th for longer."""
    T = actions.shape[0]
    cum = np.cumsum(realised_cash)
    step = 1 if T <= 30 * 48 else 4
    rows: list[dict] = []
    for t in range(0, T, step):
        rows.append({
            "ts": slot_starts[t].isoformat(),
            "soc_mwh": round(float(soc[t]), 2),
            "action_mw": round(float(actions[t]) / HOURS_PER_SLOT, 3),
            "mid_jpy_kwh": round(float(mid_kwh[t]), 4),
            "cash_jpy": round(float(realised_cash[t]), 2),
            "cum_jpy": round(float(cum[t]), 2),
        })
    return rows


def run_backtest(
    backtest_id: UUID,
    *,
    spread_jpy_kwh: float = 2.0,
    naive_buy: float | None = None,
    naive_sell: float | None = None,
) -> BacktestResult:
    """End-to-end backtest. Persists all metrics + trade rows. Audits via compute_runs."""
    with compute_run("backtest") as run:
        run.set_input({
            "backtest_id": str(backtest_id),
            "spread_jpy_kwh": spread_jpy_kwh,
        })
        t0 = time.time()
        with connect() as conn, conn.cursor() as cur:
            advisory_lock(cur, f"backtest_{backtest_id}")
            row = _load_backtest_row(cur, backtest_id)
            asset = _load_asset_spec(cur, row["asset_id"])
            area_id = _load_asset_area(cur, row["asset_id"])
            realised_kwh, stack_kwh, slot_starts = _load_window_prices(
                cur, area_id, row["window_start"], row["window_end"],
            )
            cur.execute(
                "update backtests set status='running' where id = %s",
                (str(backtest_id),),
            )
            conn.commit()

        n_slots = realised_kwh.shape[0]
        if n_slots < 48:
            err = f"window has only {n_slots} half-hour slots; need ≥ 48 (1 day)"
            _mark_failed(backtest_id, err)
            run.set_output({"error": err})
            raise RuntimeError(err)

        # Strategy dispatch (heavy compute outside the transaction).
        strategy_name: StrategyName = row["strategy"]   # type: ignore[assignment]
        if strategy_name == "naive_spread":
            from .strategies import NaiveSpreadStrategy
            strategy = NaiveSpreadStrategy(naive_buy, naive_sell)
        else:
            strategy = get_strategy(strategy_name)
        if strategy_name == "lsm_vlstm":
            from .vlstm_paths import load_vlstm_paths_per_origin
            vlstm_paths = load_vlstm_paths_per_origin(
                area_id, slot_starts, lookahead_slots=48, roll_interval_slots=24,
            )
            soc_mwh, actions_mwh = strategy.dispatch(  # type: ignore[call-arg]
                asset, realised_kwh,
                stack_prices_jpy_kwh=stack_kwh,
                vlstm_paths_per_origin=vlstm_paths,
            )
        else:
            soc_mwh, actions_mwh = strategy.dispatch(
                asset, realised_kwh, stack_prices_jpy_kwh=stack_kwh,
            )
        # Align lengths (some strategies may pad differently).
        actions_mwh = actions_mwh[:n_slots]
        soc_mwh = soc_mwh[: n_slots + 1]

        # Slippage model.
        modelled_jpy, realised_jpy = linear_bid_ask(
            actions_mwh, realised_kwh * KWH_PER_MWH, spread_jpy_kwh,
        )
        modelled_total = float(modelled_jpy.sum())
        realised_total = float(realised_jpy.sum())
        slippage_total = modelled_total - realised_total
        sharpe = _compute_sharpe(realised_jpy)
        max_dd = _compute_max_drawdown(realised_jpy)
        trade_rows = _build_trade_rows(
            slot_starts, soc_mwh, actions_mwh, realised_kwh, realised_jpy,
        )
        runtime = time.time() - t0

        # Persist.
        with connect() as conn, conn.cursor() as cur:
            advisory_lock(cur, f"backtest_persist_{backtest_id}")
            cur.execute(
                """
                update backtests set
                  status = 'done',
                  realised_pnl_jpy = %s,
                  modelled_pnl_jpy = %s,
                  slippage_jpy = %s,
                  sharpe = %s,
                  max_drawdown_jpy = %s,
                  trades_jsonb = %s::jsonb,
                  completed_at = now()
                where id = %s
                """,
                (
                    realised_total, modelled_total, slippage_total,
                    sharpe, max_dd, json.dumps(trade_rows),
                    str(backtest_id),
                ),
            )
            conn.commit()

        result = BacktestResult(
            backtest_id=str(backtest_id),
            strategy=strategy_name,
            status="done",
            realised_pnl_jpy=realised_total,
            modelled_pnl_jpy=modelled_total,
            slippage_jpy=slippage_total,
            sharpe=sharpe,
            max_drawdown_jpy=max_dd,
            runtime_seconds=runtime,
            n_slots=n_slots,
        )
        run.set_output(result.model_dump(mode="json"))
        logger.info(
            "backtest %s [%s]: realised=%.0f modelled=%.0f slip=%.0f sharpe=%.2f mdd=%.0f in %.2fs",
            backtest_id, strategy_name, realised_total, modelled_total,
            slippage_total, sharpe, max_dd, runtime,
        )
        return result


def _mark_failed(backtest_id: UUID, error_text: str) -> None:
    """Idempotent failure mark."""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "update backtests set status='failed', error=%s, completed_at=now() where id = %s",
                (error_text[:2000], str(backtest_id)),
            )
            conn.commit()
    except Exception:
        logger.exception("failed to mark backtest %s failed", backtest_id)


def mark_failed(backtest_id: UUID, error_text: str) -> None:
    _mark_failed(backtest_id, error_text)
