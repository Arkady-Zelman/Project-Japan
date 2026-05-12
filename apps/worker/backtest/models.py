"""Pydantic schemas for the backtest engine — request + result + decision row."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StrategyName = Literal["lsm", "intrinsic", "rolling_intrinsic", "naive_spread", "lsm_vlstm"]


class BacktestRequest(BaseModel):
    """Operator-supplied backtest spec; mirrors the `backtests` row inputs."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    strategy: StrategyName
    window_start: date
    window_end: date
    spread_jpy_kwh: float = Field(ge=0, default=2.0)
    # Naive-spread thresholds. Defaulted from realised history if omitted.
    naive_buy_threshold_jpy_kwh: float | None = None
    naive_sell_threshold_jpy_kwh: float | None = None


class BacktestResult(BaseModel):
    """Return shape from runner.run_backtest. Mirrors the persisted row."""

    model_config = ConfigDict(extra="forbid")

    backtest_id: str
    strategy: StrategyName
    status: Literal["done", "failed"]
    realised_pnl_jpy: float
    modelled_pnl_jpy: float
    slippage_jpy: float
    sharpe: float
    max_drawdown_jpy: float
    runtime_seconds: float
    n_slots: int
    error: str | None = None


class TradeRow(BaseModel):
    """One slot in `trades_jsonb`. Stored as a list of dicts (compact JSON)."""

    model_config = ConfigDict(extra="forbid")

    ts: datetime
    soc_mwh: float
    action_mw: float
    mid_price_jpy_kwh: float
    realised_cash_jpy: float
    cumulative_realised_jpy: float
