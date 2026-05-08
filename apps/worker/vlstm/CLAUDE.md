# apps/worker/vlstm — Claude Code context

Probabilistic LSTM price forecaster — produces 1000 plausible price *paths*
(not point forecasts) per area for the next 48 half-hour slots. Path
correlation is preserved across slots within a path; that's the whole point
and the architectural linchpin for M7 LSM dispatch.

Outputs:
- One row per training run in `models` (`type='vlstm'`, single shared
  cross-area model with area embedding) carrying RMSE/MAPE/CRPS per area
  per horizon plus the AR(1) baseline gate comparison.
- Forecast inference writes one `forecast_runs` row per area + 1000 × 48
  rows to `forecast_paths` per run, twice daily.

Consumers:
- M7 LSM reads `forecast_paths` for each path × slot to evaluate dispatch.
- M8 backtest replays historical paths against actuals.
- Dashboard Section B fan chart reads aggregated percentiles directly.

## Modules

| File | Purpose |
| --- | --- |
| `models.py` | Pydantic for FeatureWindow + ForecastRun + ForecastPathRow. |
| `data.py` | 5-block feature builder. `build_inference_window(area, origin)` for forecast.py; `build_training_examples(start, end, areas)` sliding-window iterator for train.py. Mirrors `stack/build_curve._load_area_cache` bulk-fetch pattern. |
| `model.py` | `JEPXForecaster` Lightning module + `MCDropout` (active in eval) + area embedding. Direct multi-step head: 168-slot lookback × 53 features → 48 forecast residuals. |
| `baseline.py` | AR(1) per area on raw price. Gate baseline. |
| `train.py` | Modal GPU L4 weekly training. Parquet export, Lightning fit, hold-out eval, AR(1) comparison, gate decision, Storage upload. |
| `forecast.py` | Modal CPU twice-daily inference. 9 areas × 1000 paths × 48 slots in <60s; bulk-insert `forecast_runs` + `forecast_paths`. |
| `validate.py` | Standalone gate-replay harness from persisted `models.metrics`. |

## Discipline

- **Use `common.db.connect()`** — same rule as ingest + stack + regime.
- **Wrap training in `compute_run("vlstm_train")`** and inference in
  `compute_run("forecast_inference")` so the dashboard sees them.
- **One MC-Dropout mask per forward pass, NOT per timestep.** This is the
  spec's hard requirement (§7.5 step 3). Without it, MC dropout's stochastic
  correlation breaks down and the LSM (M7) produces incorrect path-dependent
  valuations. `MCDropout` overrides `eval()` so dropout stays active during
  inference. Verify by checking that two consecutive `forward(x)` calls on
  `model.eval()` give different outputs (`var > 1e-6`).
- **Direct multi-step forecasting** (linear head produces all 48 horizons in
  one shot), not autoregressive iteration. Autoregressive loops compound
  prediction noise and break the one-mask-per-path semantics.
- **Train on log-residual transform** `r_t = log(price / stack)`. The M4
  stack output is the deterministic baseline; LSTM learns the residual
  fundamentals/sentiment process. Reconstruct raw prices at inference via
  `exp(residual_path) * stack_kwh_horizon`.
- **Bulk-fetch per area** like `stack/build_curve._load_area_cache`. Per-slot
  DB roundtrips will time out the Tokyo pooler — see SESSION_LOG_2026-05-06
  for the diagnostic trail.
- **`forecast_paths` UPSERT volume**: 9 × 1000 × 48 = 432K rows per run.
  Use `cur.executemany(..., chunk=1000)`. Two pooler round-trips per chunk.

## Don't

- Don't use 9 per-area models. One shared model with an 8-dim area
  embedding is simpler ops + better feature efficiency (research-recommended;
  Ziel & Weron 2018; M5.5 research agent flagged this).
- Don't add LSTM hidden-size > 256 without evidence it helps. The 128-hidden
  2-layer architecture is well-trodden for this problem class.
- Don't use raw prices as the training target. Log-residual against the
  stack baseline is the M5-aligned transform.
- Don't import from `lsm/` or `agent/` — VLSTM is upstream of both.
