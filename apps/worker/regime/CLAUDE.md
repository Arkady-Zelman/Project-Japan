# apps/worker/regime — Claude Code context

3-regime Markov regime-switching (MRS) model layered on top of the M4 stack
output. Janczura-Weron 2010 specification: **base** (mean-reverting trading),
**spike** (heavy-tailed independent jumps), **drop** (oversupply events).

Outputs:
- One row per area in `models` table (`type='mrs'`) carrying calibrated
  hyperparameters (regime means, variances, transition matrix, regime label
  mapping).
- One row per (area, slot, model_version) in `regime_states` carrying the
  posterior probabilities (p_base, p_spike, p_drop) and the most-likely
  regime label.

Consumers:
- M6 VLSTM uses regime probabilities as a feature input.
- M6 forecast fan chart can color by `most_likely_regime`.
- The `/dashboard` regime panel renders a stacked-area strip from
  `regime_states` directly.

## Modules

| File | Purpose |
| --- | --- |
| `models.py` | Pydantic for ModelRow + RegimeStateRow. |
| `mrs_calibrate.py` | Per-area MRS fit via `statsmodels.tsa.regime_switching.markov_regression`. Persists one `models` row per area. |
| `infer_state.py` | Hamilton's filter forward + Kim's smoother backward via `result.smoothed_marginal_probabilities`. Persists `regime_states`. |
| `validate.py` | April 2026 spike-window gate. P(spike) ≥ 0.7 on ≥80% of TK and TH spike slots (realised > ¥30/kWh) — see BUILD_SPEC §12 M5 (amended 2026-05-07). |

## Discipline

- **Use `common.db.connect()`** — same rule as ingest + stack.
- **Wrap calibration in `compute_run("regime_calibrate")`** and inference in
  `compute_run("regime_infer")` so the dashboard sees them.
- **Per-area `advisory_lock(cur, "regime_<area>")`** — concurrent fits on the
  same area corrupt audit accounting.
- **Pre-fit transform: `log(price_kwh / modelled_stack_kwh)`.** The M4 stack
  output is the deterministic baseline, so the residual is pure regime/sentiment.
  Slots where either side is null/non-positive are dropped from the fit.
- **Identify regimes by sorted means.** statsmodels returns regimes in an
  arbitrary order. Sort `result.params[trend_indices]` ascending — the lowest
  is `drop`, middle is `base`, highest is `spike`. Persist the index→label
  mapping in `models.hyperparams.regime_mapping` so `infer_state.py` can decode.

## Don't

- Don't re-fit on every cron firing. Recalibrate weekly (Sun 03:00 JST per
  spec §7.5). Daily runs only refresh `regime_states` for new slots using
  the latest `models` row.
- Don't write the same `(area, slot)` under multiple model_versions without a
  cleanup. The PK (area_id, slot_start, model_version) allows it, but stale
  rows accumulate. Mark old `models` rows `status='deprecated'` and the
  dashboard query joins on `status='ready'`.
- Don't import from `lsm/`, `vlstm/`, `agent/` — the regime engine is upstream.
