# apps/worker/backtest — Claude Code context

Strategy backtest engine. Replays four strategies on realised JEPX history
per BUILD_SPEC §12 M8: LSM, intrinsic (perfect foresight), rolling-intrinsic
(24h lookahead of realised prices), naive-spread (price threshold rule).
Applies a slippage model, computes equity curves + Sharpe + max drawdown,
persists one `backtests` row per (asset, window, strategy) tuple.

## Modules

| File | Purpose |
| --- | --- |
| `models.py` | Pydantic for `BacktestRequest`, `BacktestResult`. |
| `slippage.py` | Linear bid-ask half-spread model: charge price = mid + spread/2; discharge price = mid − spread/2. Operator-configurable spread (default ¥2/kWh round-trip). |
| `strategies.py` | Four strategy classes with a common `dispatch(...)` signature returning `(soc_path, action_path, gross_cashflows)`. |
| `runner.py` | Orchestration: load asset + realised prices, call strategy, apply slippage, compute Sharpe + drawdown, persist. Wraps in `compute_run("backtest")`. |

## Discipline

- **Use `common.db.connect()`** everywhere — same rule as ingest + stack + regime + vlstm + lsm.
- **Wrap each backtest run in `compute_run("backtest")`** so the dashboard sees them.
- **Per-backtest `advisory_lock(cur, f"backtest_{backtest_id}")`** — concurrent retries on the same row race on the UPSERT.
- **Strategies operate on plain ndarrays.** No DB access from inside the strategy class. The runner pulls all inputs into memory and feeds the strategy.
- **Realised prices come from `jepx_spot_prices`** (auction='day_ahead', price_jpy_kwh, area-filtered). Stack model output (for LSMStackStrategy) comes from `stack_clearing_prices` over the same window.
- **Slippage is applied AFTER the strategy decides actions.** Strategy sees mid prices; slippage adjusts realised cash flow per direction.
- **Sharpe annualisation**: half-hourly returns aggregated to daily, daily Sharpe × √365 for the displayed annualised number.
- **Max drawdown**: peak-to-trough on the cumulative-cash equity curve, in raw ¥.

## Don't

- Don't import from `agent/` — backtest is upstream.
- Don't add state-of-charge to slippage (e.g., "deeper SoC costs more"). v1 is symmetric linear half-spread regardless of SoC.
- Don't run backtests on schedule — operator triggers via `/lab` UI or `modal run …::run_backtest_run`.
- Don't pass Pydantic models to numpy operations. Convert AssetSpec → ndarray params in the runner.
