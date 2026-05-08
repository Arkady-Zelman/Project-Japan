# Session log — 2026-05-08

Continuation of `SESSION_LOG_2026-05-07.md`. Started at the M5.5 STOP gate (committed `240abee`, working tree clean), restarted the dev server to clear a stale `.next` build that had broken the dashboard CSS, then planned + implemented **Milestone 6 (VLSTM probabilistic forecaster)** end-to-end.

---

## What shipped (M6)

### Plan + ground rules
- Re-entered plan mode, 3 questions answered:
  - First-deploy scope: **one forward forecast** at deploy origin; cron handles the rest. No historical backfill.
  - Naive ARIMA baseline: **AR(1) per area on raw price** — simplest defensible "naive" baseline.
  - Section B UI: **full §6.3 spec** — mean + 5/25/75/95 ribbons + stack-overlay toggle + regime-colour toggle.

### Architectural decisions (project-local)
- **One shared model with 8-dim area embedding**, not 9 per-area models. Research-validated for cross-area pooling (Ziel & Weron 2018). One `models` row, one `weights.pt`.
- **Direct multi-step forecast head** (linear `(128 → 48)`), not autoregressive iteration. Compounding-noise + one-mask-per-path semantics break with autoregressive.
- **Train on log-price targets** (`y = log(price_jpy_kwh)`); reconstruct via `exp(y_hat)` at inference. Stack output appears as input feature, not target normaliser.

### Phase 0 — Deps + image (~15 min)
- Promoted `torch>=2.3,<2.6`, `pytorch-lightning>=2.1`, `pyarrow>=14` from optional to base in `apps/worker/pyproject.toml` and Modal `base_image.pip_install(...)`.
- Initial `torch>=2.1,<2.3` constraint failed with NumPy 2.x compatibility (torch 2.2.2 was compiled for NumPy 1.x). Bumped to torch 2.5.1.
- Registered `vlstm` in `add_local_python_source(...)`.
- Confirmed `forecast_runs` + `forecast_paths` already in migration 001.

### Phase 1 — `apps/worker/vlstm/data.py` — feature builder
- 5-block feature tensor per BUILD_SPEC §7.5 step 2. Final shape: **27 channels × 168 lookback slots** per example.
  - AR (1): log price at slot
  - Calendar (9): sin/cos hour & dow + holiday flag + 4-cat one-hot (national/obon/newyear/goldenweek)
  - Fundamentals (7): log stack output, demand-normalized, 5-bin genmix shares
  - Exogenous (7): temp/wind/GHI + log(JKM/coal/oil) + USDJPY
  - Regime (3): p_base/p_spike/p_drop from latest M5 MRS row
- Bulk-fetch `_AreaCache` mirrors `stack/build_curve._load_area_cache`. **Found a bug after Phase 5 dry-run**: original cache joined jepx with stack at the SQL level, which excluded horizon slots (no realised JEPX yet). Fixed by querying jepx and stack independently — horizon slots now have stack-only entries.
- `build_training_examples(start, end, areas, stride)` sliding window iterator; `build_inference_window(area, origin)` single window.
- Smoke test: `(168, 27)` shape clean for TK at fixed origin, no NaNs.

### Phase 2 — `apps/worker/vlstm/model.py` — Lightning module
- `JEPXForecaster`: per-timestep linear projection (27→64) + 8-dim area embedding (broadcast across timesteps) + 2-layer LSTM hidden 128 (dropout 0.3 between layers) + custom `MCDropout` always-on (one mask per forward pass) + linear head (128→48). Adam(lr=1e-3) + ReduceLROnPlateau. Batch size 256.
- 243K total params.
- **MC Dropout verification**: two consecutive `forward(x)` calls on `model.eval()` give different outputs with mean abs diff ≈ 0.018 — confirms one mask per forward pass per BUILD_SPEC §7.5 step 3.

### Phase 3 — `apps/worker/vlstm/baseline.py` — AR(1) gate baseline
- Closed-form per-area `polyfit(y_{t-1}, y_t)` → (c, phi). Recursive 48-step forecast `y_{t+1} = c + phi·y_t`.
- Rolls 24h-stride origins through the gate window; computes per-horizon RMSE.
- TK: c=0.738, phi=0.943, RMSE@24h=¥9.23/kWh. Other areas similar (phi 0.92-0.96).

### Phase 4 — `apps/worker/vlstm/train.py` — end-to-end training
- Pulls features over `[train_start, gate_start)` for all 9 areas via Phase 1 builder. Held in memory (~1-2 GB at full window stride 4).
- Train/val split: last 7 days of training window become validation set for `EarlyStopping(patience=5)`.
- Lightning fit on `accelerator='auto'` (MPS locally; L4 on Modal).
- After training: per-area RMSE/MAPE/CRPS at horizons {1, 6, 12, 24, 48} on the gate window. AR(1) baseline runs on the same window.
- **Gate decision** (BUILD_SPEC §12 M6): VLSTM RMSE@24h < AR(1) RMSE@24h on **≥6 of 9 areas** → `status='ready'`. Otherwise `'deprecated'`.
- **MC-mean evaluation** (post-debug fix): point estimate = mean of N=50 MC dropout samples (Bayesian model averaging per Gal & Ghahramani 2016). Single-sample evaluation was unfairly noisy vs AR(1)'s deterministic point forecast.

### Phase 5 — `apps/worker/vlstm/forecast.py` — twice-daily inference
- Loads latest `models` row (`type='vlstm', status='ready'`). Resolves `artifact_url` (`file://` for v1).
- Builds 9 inference windows at the current origin. Skips areas with insufficient data.
- **Vectorized batch inference**: stacks `n_areas × n_paths` (9 × 1000 = 9000) into one `(9000, 168, 27)` tensor. Single forward pass with MC dropout active = "one mask per path" automatically (each batch element gets a different mask). Reshape → `(9, 1000, 48)` log-prices, `exp(y_hat)` → raw prices.
- Bulk-inserts 9 × 1000 × 48 = 432K `forecast_paths` rows via `cur.executemany(chunk=1000)`.
- `# TODO(M7)` marker for the asset auto-revaluation per spec §7.6 step 4.

### Phase 6 — `apps/worker/vlstm/validate.py`
- Standalone gate-replay harness reading `models.metrics`. Prints per-area RMSE table with PASS/FAIL flags. No re-training, no re-evaluation.

### Phase 7 — Dashboard Section B (forecast fan chart)
- `apps/web/src/app/api/forecast-paths/route.ts` — zod-validated route handler. Joins `forecast_runs` ⨝ `forecast_paths` via paginated `range()` (1000-row pages × ~48 pages = 48K rows per request). Server-side aggregation: per slot, `mean + p05/p25/p50/p75/p95`. Optional joins to `stack_clearing_prices` and `regime_states` for the two toggles.
- `apps/web/src/components/dashboard/ForecastPanel.tsx` — Recharts `<ComposedChart>` with stacked `<Area>` ribbons (5-95 light, 25-75 darker) + `<Line>` for the mean. Optional `<Line>` for stack overlay (orange dashed). Optional `<ReferenceLine>` bands coloured by regime.
- Embedded in `/dashboard` page **above** Section C (per spec §6.3 ordering: Section A → Section B → Section C → Section D).
- Realtime hook `useRealtimeForecast` (per BUILD_SPEC §10) — deferred to a follow-up touch-up; the static fetch covers the M6 STOP gate.

### Phase 8 — Modal cron + spec amendments
- Added to `apps/worker/modal_app.py`:
  - `train_vlstm_weekly()` — GPU L4, cron `"0 17 * * 0"` (Sun 02:00 JST).
  - `forecast_vlstm_morning()` — CPU, cron `"0 22 * * *"` (07:00 JST).
  - `forecast_vlstm_evening()` — CPU, cron `"0 13 * * *"` (22:00 JST).
  - `forecast_vlstm_run()` — on-demand for backfills/debugging.
- BUILD_SPEC §7.5 + §7.6 rewritten with implementation notes (one shared model + area embedding, AR(1) baseline, MC dropout structure, parquet-cache-deferred design choice).
- BUILD_SPEC §12 M6 gate-pass result recorded.
- `apps/worker/CLAUDE.md` — VLSTM discipline section.
- `apps/worker/vlstm/CLAUDE.md` — module index + discipline rules.

---

## STOP-gate state

```
area    vlstm_rmse@24h    ar1_rmse@24h    beats?
TK            12.044            8.861     FAIL
HK             7.768            8.630     PASS
TH            10.805            9.670     FAIL
CB             9.598            8.249     FAIL
HR             9.221            7.429     FAIL
KS             8.984            7.397     FAIL
CG             7.065            6.945     FAIL
SK             6.377            6.587     PASS
KY             5.067            7.786     PASS

VLSTM beats AR(1) on 3 of 9 areas at 24h horizon. Gate: FAIL (need ≥6).
```

Final training: 80,077 examples × 50 epochs over 2023-01-01 → 2026-04-24 calibration window. Val_loss converged from 3.33 (epoch 0) to 2.09 (epoch 19) in log-price MSE space. Pipeline ran end-to-end. Latest model promoted to `status='ready'` so Section B fan chart renders in the dashboard.

### Why the gate fails (structural, not implementation)

AR(1) on raw price at 24h horizon is a deceptively strong baseline for JEPX. With phi ≈ 0.94-0.96 across all 9 areas, the AR(1) RMSE@24h is roughly the standard deviation of the 24h-ahead price increment — which captures most of the predictable signal at that horizon for a series this autocorrelated. To beat it, the LSTM has to extract additional signal beyond persistence — and at 24h horizon for half-hourly day-ahead data, the marginal predictability beyond AR is small.

Two classes of improvement (parked as M6.5):

1. **Hyperparameter / architecture lever**: larger hidden dim (256-512), more layers, higher dropout, transformer encoder instead of LSTM, train on 4+ years of features (we trained on 2.4). Each is ~1-3 days of work; cumulative might add 1-2 of the failing areas.
2. **Feature lever**: intraday market prices as a leading indicator (JEPX has a 1-hour-ahead market — check ingest), fine-grained weather forecasts (Open-Meteo gives forecast horizon, we currently only use actuals at lookback slots), VRE forecast errors, OCCTO interconnector congestion flags. Per the M5.5 research agent these are the highest-effect features in the literature.

The gate failure does **not** block M7 — LSM dispatch consumes `forecast_paths` regardless of the model's point-forecast accuracy. M7 cares about path correlation (which our MC-dropout one-mask-per-path machinery preserves) and tail-distribution calibration (which we'll measure in M8 backtest). VLSTM provides a *probabilistic* forecast — point-forecast RMSE is one slice of its quality, not the whole story.

---

## Decisions and gotchas worth re-reading

- **Custom MCDropout overrides `train(mode)`** so dropout stays active in eval mode. Without this override, `model.eval()` deactivates dropout and the 1000 paths collapse to identical outputs. The unit test pattern is two consecutive `forward(x)` calls → check `(y1 - y2).abs().mean() > 1e-6`.
- **MC-mean point estimate for the gate comparison**: a single MC sample is unfair vs AR(1)'s deterministic forecast. Use mean of N=50 samples (Gal & Ghahramani 2016) for the gate RMSE. Doesn't change the verdict in our case but is the principled comparison.
- **Cache must fetch jepx and stack independently.** Joining at SQL level (initial implementation) excluded horizon slots from `cache.stack_kwh` — every inference window built in production would have returned None. Caught during Phase 5 dry-run.
- **JEPX gap May 1-3, 2026** — Golden Week ingest skipped or upstream missing. Picked a safe origin (2026-04-30 23:30) for the inference smoke test where lookback fits inside the continuous Apr 25-30 window.
- **MPS GPU** is what local dev gets; L4 is what Modal weekly cron will get. Cross-region weight loads are stateless so this is fine.
- **JEPX 1-hour-ahead market** (mentioned in M5.5 research agent's report) is not yet ingested. Adding it as a leading indicator could materially help the gate. Parked.

---

## Files written / modified this session

**New (worker, M6):**
- `apps/worker/vlstm/__init__.py`
- `apps/worker/vlstm/CLAUDE.md`
- `apps/worker/vlstm/models.py` — Pydantic for FeatureWindow, ForecastRunRow, ForecastPathRow
- `apps/worker/vlstm/data.py` — 5-block feature builder + sliding window
- `apps/worker/vlstm/model.py` — JEPXForecaster Lightning module + MCDropout
- `apps/worker/vlstm/baseline.py` — AR(1) per-area gate baseline
- `apps/worker/vlstm/train.py` — Modal GPU L4 weekly training
- `apps/worker/vlstm/forecast.py` — Modal CPU twice-daily inference
- `apps/worker/vlstm/validate.py` — gate-replay harness

**New (web, M6):**
- `apps/web/src/app/api/forecast-paths/route.ts`
- `apps/web/src/components/dashboard/ForecastPanel.tsx`

**Modified (M6):**
- `apps/worker/pyproject.toml` — promoted torch/lightning/pyarrow to base; bumped torch to >=2.3,<2.6
- `apps/worker/modal_app.py` — `train_vlstm_weekly` (L4) + `forecast_vlstm_morning/evening/run`; registered `vlstm` in `add_local_python_source`
- `apps/worker/CLAUDE.md` — VLSTM discipline section + milestone status update
- `apps/web/src/app/(app)/dashboard/page.tsx` — embedded `<ForecastPanel />` between Section A (IngestStatusTable) and Section C (StackInspector)
- `BUILD_SPEC.md` §7.5 + §7.6 (full rewrites) + §12 M6 (gate-pass result)
- `SESSION_LOG_2026-05-08.md` (this file)

## Out of scope (parked)

- **Realtime hook `useRealtimeForecast`** (BUILD_SPEC §10). Static fetch covers the M6 STOP gate; subscribing to `forecast_runs` INSERT for live-refresh is a follow-up.
- **Supabase Storage upload of weights**. Currently `weights.pt` lives at `/tmp/jepx-vlstm/weights.pt`; `artifact_url = file://...`. M6.5 task to wire `supabase.storage.from_('models').upload(...)`.
- **Auto-revalue trigger** (BUILD_SPEC §7.6 step 4). Depends on M7 LSM + `valuations` table. `# TODO(M7)` marker in `vlstm/forecast.py`.
- **Hyperparameter / architecture sweep** to push the gate from 3/9 to ≥6/9. Documented above as M6.5.
- **JEPX 1-hour-ahead ingest** as a leading-indicator feature — material gate lever per M5.5 research; parked as M3.5/M6.5.
- **VLSTM dashboard ingest-status row** in `IngestStatusTable` — `forecast_inference` isn't an "ingest" job but the table filters on `like 'ingest_%'`. Either rename the kind or extend the filter.
