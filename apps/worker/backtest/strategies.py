"""Four backtest strategies — common interface, varied internals.

Each strategy takes the asset spec + a window of realised prices (and
optional auxiliary inputs like stack-model forecasts for LSMStack) and
returns the per-slot SoC trajectory + actions chosen.

Common return shape:
    soc_mwh:    (T+1,)  state of charge after each slot, starting from soc_initial
    actions_mwh:(T,)    MWh charged (>0) or discharged (<0) per slot

The runner applies the slippage model to the actions to produce realised
cash flows. Strategies see the mid-price (realised JEPX) regardless of
how they internally forecast (perfect foresight, lookahead, stack model).

Sign convention matches `lsm.engine`:
- action ≥ 0 → charge → cash = −action × price (operator pays)
- action < 0 → discharge → cash = −action × price (operator receives;
  positive because action is negative)
"""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

from lsm.engine import run_lsm
from lsm.models import AssetSpec

logger = logging.getLogger("backtest.strategies")

# Half-hour JEPX slots.
HOURS_PER_SLOT = 0.5
DT_DAYS = HOURS_PER_SLOT / 24.0
KWH_PER_MWH = 1_000.0


class Strategy(Protocol):
    """Backtest strategy interface."""

    name: str

    def dispatch(
        self,
        asset: AssetSpec,
        realised_prices_jpy_kwh: np.ndarray,
        *,
        stack_prices_jpy_kwh: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return (soc_mwh shape (T+1,), actions_mwh shape (T,))."""


# ---------------------------------------------------------------------------
# 1. NaiveSpreadStrategy
# ---------------------------------------------------------------------------


class NaiveSpreadStrategy:
    """Threshold rule: charge below buy price, discharge above sell price."""

    name = "naive_spread"

    def __init__(
        self,
        buy_threshold_jpy_kwh: float | None = None,
        sell_threshold_jpy_kwh: float | None = None,
    ) -> None:
        self.buy_threshold = buy_threshold_jpy_kwh
        self.sell_threshold = sell_threshold_jpy_kwh

    def dispatch(
        self,
        asset: AssetSpec,
        realised_prices_jpy_kwh: np.ndarray,
        *,
        stack_prices_jpy_kwh: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        prices = np.asarray(realised_prices_jpy_kwh, dtype=np.float64)
        T = prices.shape[0]
        # Default thresholds = 30th / 70th percentile of the window.
        buy = (
            self.buy_threshold
            if self.buy_threshold is not None
            else float(np.percentile(prices, 30))
        )
        sell = (
            self.sell_threshold
            if self.sell_threshold is not None
            else float(np.percentile(prices, 70))
        )

        max_charge_step = asset.power_mw_charge * HOURS_PER_SLOT
        max_discharge_step = asset.power_mw_discharge * HOURS_PER_SLOT
        soc = np.empty(T + 1, dtype=np.float64)
        actions = np.zeros(T, dtype=np.float64)
        soc[0] = asset.soc_initial_mwh

        for t in range(T):
            v = soc[t]
            p = prices[t]
            if p < buy and v < asset.soc_max_mwh:
                a = min(max_charge_step, asset.soc_max_mwh - v)
            elif p > sell and v > asset.soc_min_mwh:
                a = -min(max_discharge_step, v - asset.soc_min_mwh)
            else:
                a = 0.0
            actions[t] = a
            soc[t + 1] = v + a
        return soc, actions


# ---------------------------------------------------------------------------
# 2. IntrinsicStrategy (perfect foresight, single LSM run on the whole window)
# ---------------------------------------------------------------------------


class IntrinsicStrategy:
    """LSM on realised prices as if they were the only path. Upper bound."""

    name = "intrinsic"

    def dispatch(
        self,
        asset: AssetSpec,
        realised_prices_jpy_kwh: np.ndarray,
        *,
        stack_prices_jpy_kwh: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        prices = np.asarray(realised_prices_jpy_kwh, dtype=np.float64) * KWH_PER_MWH
        T = prices.shape[0]
        # Engine wants (M, T+1). With realised history we have T prices total
        # (the slots themselves); pad by repeating the last price as the
        # post-horizon "anchor" since no decision is made at the very last slot.
        paths = np.empty((1, T + 1), dtype=np.float64)
        paths[0, :T] = prices
        paths[0, T] = prices[-1]

        result = run_lsm(
            paths=paths, asset=asset,
            n_volume_grid=51, basis="power", dt_days=DT_DAYS, discount_rate=0.0,
        )
        # slot_mean_action_mw is in MW (rate). Convert to MWh per slot.
        actions_mw = np.array(result.slot_mean_action_mw, dtype=np.float64)
        actions_mwh = actions_mw * HOURS_PER_SLOT
        soc_mwh = np.array(result.slot_mean_soc_mwh, dtype=np.float64)
        return soc_mwh[: T + 1], actions_mwh[:T]


# ---------------------------------------------------------------------------
# 3. RollingIntrinsicStrategy (rolling 24h-lookahead of realised prices)
# ---------------------------------------------------------------------------


def _roll_horizon_lsm(
    asset: AssetSpec,
    forecast_paths_per_origin: list[np.ndarray],
    realised_prices_jpy_mwh: np.ndarray,
    origin_indices: list[int],
    initial_soc_mwh: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Helper for rolling strategies. Run LSM at each origin with the
    given forecast (1 path × horizon), take the first action, advance one
    slot, repeat. Between origins the same recently-computed action is
    re-applied (held constant).

    `forecast_paths_per_origin[i]` is the 1-path future-price ndarray for
    origin i (shape (1, H+1) where H is the lookahead horizon). The
    realised price at each slot is what actually clears.

    Returns (soc_mwh shape (T+1,), actions_mwh shape (T,)).
    """
    T = realised_prices_jpy_mwh.shape[0]
    soc = np.empty(T + 1, dtype=np.float64)
    actions = np.zeros(T, dtype=np.float64)
    soc[0] = initial_soc_mwh

    # Sort origins ascending (just in case); sentinel at end.
    sorted_origins = sorted(set(origin_indices))
    if sorted_origins[0] != 0:
        sorted_origins = [0, *sorted_origins]

    cur_action_per_slot = 0.0
    next_origin_idx = 0
    for t in range(T):
        # Refresh the action plan whenever we cross an origin.
        if next_origin_idx < len(sorted_origins) and t >= sorted_origins[next_origin_idx]:
            origin = sorted_origins[next_origin_idx]
            forecast = forecast_paths_per_origin[next_origin_idx]
            # Build a fresh AssetSpec with current SoC as the starting point.
            stub_asset = asset.model_copy(update={"soc_initial_mwh": soc[t]})
            try:
                result = run_lsm(
                    paths=forecast, asset=stub_asset,
                    n_volume_grid=51, basis="power",
                    dt_days=DT_DAYS, discount_rate=0.0,
                )
                # Take just the first action from the rolled LSM.
                cur_action_per_slot = float(result.slot_mean_action_mw[0]) * HOURS_PER_SLOT
            except Exception as e:
                logger.warning("rolling LSM at origin %d failed: %s", origin, e)
                cur_action_per_slot = 0.0
            next_origin_idx += 1

        # Apply the most recent action (constrained to current SoC bounds).
        a = cur_action_per_slot
        a = max(-asset.power_mw_discharge * HOURS_PER_SLOT,
                min(asset.power_mw_charge * HOURS_PER_SLOT, a))
        if a > 0:
            a = min(a, asset.soc_max_mwh - soc[t])
        else:
            a = max(a, asset.soc_min_mwh - soc[t])
        actions[t] = a
        soc[t + 1] = soc[t] + a
        # Don't reuse the same action indefinitely — at the next origin we
        # recompute. Between origins, hold (don't keep charging/discharging
        # past one slot since the LSM call gave us only the first decision).
        cur_action_per_slot = 0.0

    return soc, actions


# Roll a fresh LSM every 2 slots (1 hour) — captures intraday opportunities
# without becoming compute-prohibitive.
DEFAULT_ROLL_INTERVAL_SLOTS = 2
DEFAULT_LOOKAHEAD_SLOTS = 48


class RollingIntrinsicStrategy:
    """Rolls a 48-slot LSM at every roll-interval, using realised future prices."""

    name = "rolling_intrinsic"

    def dispatch(
        self,
        asset: AssetSpec,
        realised_prices_jpy_kwh: np.ndarray,
        *,
        stack_prices_jpy_kwh: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        prices_jpy_mwh = np.asarray(realised_prices_jpy_kwh, dtype=np.float64) * KWH_PER_MWH
        T = prices_jpy_mwh.shape[0]
        H = min(DEFAULT_LOOKAHEAD_SLOTS, T)
        origin_indices = list(range(0, T - H + 1, DEFAULT_ROLL_INTERVAL_SLOTS))
        forecasts = []
        for origin in origin_indices:
            window = prices_jpy_mwh[origin: origin + H + 1]
            if window.shape[0] < H + 1:
                # Pad with last price for the trailing window.
                pad = np.full(H + 1 - window.shape[0], window[-1])
                window = np.concatenate([window, pad])
            forecasts.append(window.reshape(1, -1))
        return _roll_horizon_lsm(
            asset=asset,
            forecast_paths_per_origin=forecasts,
            realised_prices_jpy_mwh=prices_jpy_mwh,
            origin_indices=origin_indices,
            initial_soc_mwh=asset.soc_initial_mwh,
        )


# ---------------------------------------------------------------------------
# 4. LSMStackStrategy (rolling LSM with M4 stack model as forecast)
# ---------------------------------------------------------------------------


class LSMStackStrategy:
    """Rolls a 48-slot LSM at every roll-interval, using stack-model prices.

    Causally honest: at each origin, the only future prices the strategy
    uses are the M4 stack model output for the next 48 slots — no peek
    at realised. The realised price is what clears, but the strategy
    decides actions on the basis of the stack forecast only.
    """

    name = "lsm"

    def dispatch(
        self,
        asset: AssetSpec,
        realised_prices_jpy_kwh: np.ndarray,
        *,
        stack_prices_jpy_kwh: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        if stack_prices_jpy_kwh is None:
            raise ValueError("LSMStackStrategy requires stack_prices_jpy_kwh")
        realised_jpy_mwh = np.asarray(realised_prices_jpy_kwh, dtype=np.float64) * KWH_PER_MWH
        stack_jpy_mwh = np.asarray(stack_prices_jpy_kwh, dtype=np.float64) * KWH_PER_MWH
        T = realised_jpy_mwh.shape[0]
        H = min(DEFAULT_LOOKAHEAD_SLOTS, T)
        origin_indices = list(range(0, T - H + 1, DEFAULT_ROLL_INTERVAL_SLOTS))
        forecasts = []
        for origin in origin_indices:
            window = stack_jpy_mwh[origin: origin + H + 1]
            if window.shape[0] < H + 1:
                pad_value = window[-1] if len(window) > 0 else realised_jpy_mwh[origin]
                pad = np.full(H + 1 - window.shape[0], pad_value)
                window = np.concatenate([window, pad])
            forecasts.append(window.reshape(1, -1))
        return _roll_horizon_lsm(
            asset=asset,
            forecast_paths_per_origin=forecasts,
            realised_prices_jpy_mwh=realised_jpy_mwh,
            origin_indices=origin_indices,
            initial_soc_mwh=asset.soc_initial_mwh,
        )


# ---------------------------------------------------------------------------
# 5. LSMVLSTMStrategy (M10C L5 — rolling LSM with VLSTM forecast paths)
# ---------------------------------------------------------------------------


class LSMVLSTMStrategy:
    """Rolling LSM using VLSTM forecast_paths as the per-origin forecast.

    Aux input `vlstm_paths_per_origin` is a list of (P, H+1) ndarrays in
    JPY/kWh, one per roll origin. Falls back to stack-driven LSM when the
    list element at a given origin is None or empty.
    """

    name = "lsm_vlstm"

    def dispatch(
        self,
        asset: AssetSpec,
        realised_prices_jpy_kwh: np.ndarray,
        *,
        stack_prices_jpy_kwh: np.ndarray | None = None,
        vlstm_paths_per_origin: list[np.ndarray | None] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        if vlstm_paths_per_origin is None:
            raise ValueError("LSMVLSTMStrategy requires vlstm_paths_per_origin")
        realised_jpy_mwh = np.asarray(realised_prices_jpy_kwh, dtype=np.float64) * KWH_PER_MWH
        stack_jpy_mwh = (
            np.asarray(stack_prices_jpy_kwh, dtype=np.float64) * KWH_PER_MWH
            if stack_prices_jpy_kwh is not None
            else None
        )
        T = realised_jpy_mwh.shape[0]
        H = min(DEFAULT_LOOKAHEAD_SLOTS, T)
        origin_indices = list(range(0, T - H + 1, DEFAULT_ROLL_INTERVAL_SLOTS))
        forecasts: list[np.ndarray] = []
        for i, origin in enumerate(origin_indices):
            vp = vlstm_paths_per_origin[i] if i < len(vlstm_paths_per_origin) else None
            if vp is not None and vp.shape[0] > 0:
                # Use the path-mean across the P sampled paths as the forecast
                # curve; matches the LSMStack contract of a single forecast
                # series per origin. Shape (1, H+1) in JPY/MWh.
                mean_curve = vp.mean(axis=0) * KWH_PER_MWH
                if mean_curve.shape[0] >= H + 1:
                    forecasts.append(mean_curve[: H + 1].reshape(1, -1))
                    continue
                pad_value = mean_curve[-1] if mean_curve.shape[0] else realised_jpy_mwh[origin]
                pad = np.full(H + 1 - mean_curve.shape[0], pad_value)
                forecasts.append(np.concatenate([mean_curve, pad]).reshape(1, -1))
                continue
            # Fall back to stack model.
            if stack_jpy_mwh is None:
                forecasts.append(realised_jpy_mwh[origin: origin + H + 1].reshape(1, -1))
                continue
            window = stack_jpy_mwh[origin: origin + H + 1]
            if window.shape[0] < H + 1:
                pad_value = window[-1] if len(window) > 0 else realised_jpy_mwh[origin]
                pad = np.full(H + 1 - window.shape[0], pad_value)
                window = np.concatenate([window, pad])
            forecasts.append(window.reshape(1, -1))
        return _roll_horizon_lsm(
            asset=asset,
            forecast_paths_per_origin=forecasts,
            realised_prices_jpy_mwh=realised_jpy_mwh,
            origin_indices=origin_indices,
            initial_soc_mwh=asset.soc_initial_mwh,
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "naive_spread": NaiveSpreadStrategy,
    "intrinsic": IntrinsicStrategy,
    "rolling_intrinsic": RollingIntrinsicStrategy,
    "lsm": LSMStackStrategy,
    "lsm_vlstm": LSMVLSTMStrategy,
}


def get_strategy(name: str) -> Strategy:
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"unknown strategy: {name}")
    return cls()  # type: ignore[no-any-return]
