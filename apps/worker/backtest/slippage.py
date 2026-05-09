"""Slippage model — linear bid-ask half-spread.

For each slot the operator pays a price `mid + spread/2` when charging
(action_mw > 0) and receives `mid − spread/2` when discharging
(action_mw < 0). The slippage cost is the gap between this realised cash
flow and the mid-price modelled cash flow, both relative to the same
absolute action.

Sign convention (matches `lsm.engine`):
- action ≥ 0 (charging): cash_flow = −action × price (cost — operator pays).
  realised_price = mid + spread/2 → realised_cash = −action × (mid + spread/2).
  modelled_cash = −action × mid.
  slippage_cost = modelled − realised = +action × spread/2 ≥ 0. (Operator pays more.)
- action < 0 (discharging): cash_flow = −action × price (revenue, since action < 0).
  realised_price = mid − spread/2 → realised_cash = −action × (mid − spread/2).
  modelled_cash = −action × mid.
  slippage_cost = modelled − realised = +action × spread/2.
  Since action < 0, slippage_cost is negative; means operator receives less revenue.
  The absolute cost is |action| × spread/2, always positive in slippage-budget terms.

We track `slippage_jpy = sum(|action| × spread/2)` for the report — total
gap between mid-price modelled P&L and realised P&L. By construction
`realised_pnl = modelled_pnl − slippage_jpy`.
"""

from __future__ import annotations

import numpy as np

# Convert per-kWh to per-MWh for the engine (which works in MWh).
KWH_PER_MWH = 1_000.0


def linear_bid_ask(
    actions_mwh: np.ndarray,
    mid_prices_jpy_mwh: np.ndarray,
    spread_jpy_kwh: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply linear half-spread to per-slot actions.

    Args:
      actions_mwh: (T,) ndarray of MWh actions per slot. >0 charge, <0 discharge.
      mid_prices_jpy_mwh: (T,) ndarray of clearing prices in JPY/MWh.
      spread_jpy_kwh: round-trip half-spread parameter, ¥/kWh. The half-spread
        applied per side is `spread_jpy_kwh × KWH_PER_MWH / 2`.

    Returns:
      (modelled_cash_jpy, realised_cash_jpy): each shape (T,). Per-slot
      cash flow before and after slippage. Sum to get total P&L.

      `slippage_jpy = sum(modelled_cash - realised_cash) = sum(|action| * half_spread_jpy_mwh)`.
    """
    actions = np.asarray(actions_mwh, dtype=np.float64)
    mids = np.asarray(mid_prices_jpy_mwh, dtype=np.float64)
    half_spread_jpy_mwh = spread_jpy_kwh * KWH_PER_MWH / 2.0

    # Modelled cash: -action * mid (charge=cost, discharge=revenue).
    modelled = -actions * mids
    # Realised cash: charge pays mid+½spread, discharge receives mid-½spread.
    # In both cases the operator is worse off by |action| × ½spread.
    realised = modelled - np.abs(actions) * half_spread_jpy_mwh
    return modelled, realised


def total_slippage_jpy(actions_mwh: np.ndarray, spread_jpy_kwh: float) -> float:
    """Sum of |action| × ½spread across all slots, in JPY."""
    half_spread_jpy_mwh = spread_jpy_kwh * KWH_PER_MWH / 2.0
    return float(np.sum(np.abs(actions_mwh)) * half_spread_jpy_mwh)
