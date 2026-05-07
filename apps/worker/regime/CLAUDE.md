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
| `jw_mrs.py` | `JanczuraWeronMRS` class: 3-regime MRS with posterior-weighted regime labeling + biased-init candidate ladder + AR(1) fallback. |
| `pot.py` | `PeaksOverThreshold` class: two-sided GPD on residual tails + empirical-CDF-rank tail probability. Lifts MRS posterior on sparse-tail spike events. |
| `mrs_calibrate.py` | Per-area calibration. Runs MRS + POT, combines via `p_spike = max(p_mrs, p_pot)`, renormalises, persists `models` + `regime_states` atomically. |
| `infer_state.py` | Hamilton's filter forward + Kim's smoother backward, plus POT pass. Daily refresh of `regime_states`. |
| `validate.py` | April 2026 spike-window gate. P(spike) ≥ 0.7 on ≥80% of TK and TH spike slots (realised > ¥30/kWh) — see BUILD_SPEC §12 M5 (amended 2026-05-07). All 9 areas reported; only TK + TH gate-fail. |

## Discipline

- **Use `common.db.connect()`** — same rule as ingest + stack.
- **Wrap calibration in `compute_run("regime_calibrate")`** and inference in
  `compute_run("regime_infer")` so the dashboard sees them.
- **Per-area `advisory_lock(cur, "regime_<area>")`** — concurrent fits on the
  same area corrupt audit accounting.
- **Pre-fit transform: `log(price_kwh / modelled_stack_kwh)`.** The M4 stack
  output is the deterministic baseline, so the residual is pure regime/sentiment.
  Slots where either side is null/non-positive are dropped from the fit.
- **Identify regimes via posterior-weighted labeling**, not by sorted means or
  variances. For each regime, compute mean P(state=k | high-price slot) over
  the historical 95th-percentile-and-above price slots in the calibration
  window; `spike` = argmax. Among the remaining two: lowest variance = `base`,
  other = `drop`. Variance-only labeling fails for areas where the spike
  events have positive residuals (e.g. TH); mean-only fails for areas where
  spike events have negative residuals (e.g. TK). Posterior-weighted handles
  both cases. Mapping persisted in `models.hyperparams.regime_mapping`.

- **POT (peaks-over-threshold) is the structural fix for skewed residuals.**
  Symmetric 3-regime Gaussian-mixture MRS allocates regimes to where the
  *mass* lives; sparse one-sided tails get no regime of their own, so MRS
  posterior P(spike) ≈ 0 on real spike events for areas like TH. POT models
  the residual tails directly (GPD on excesses) and combines with MRS via
  `p_spike = max(p_mrs, p_pot)`. We use `direction='both'` so the spike
  probability lifts on residuals far from the median in either direction —
  oversupply slots (extreme negative residual at low price) are filtered out
  by the gate's realised-price threshold anyway.

## Don't

- Don't re-fit on every cron firing. Recalibrate weekly (Sun 03:00 JST per
  spec §7.5). Daily runs only refresh `regime_states` for new slots using
  the latest `models` row.
- Don't write the same `(area, slot)` under multiple model_versions without a
  cleanup. The PK (area_id, slot_start, model_version) allows it, but stale
  rows accumulate. Mark old `models` rows `status='deprecated'` and the
  dashboard query joins on `status='ready'`.
- Don't import from `lsm/`, `vlstm/`, `agent/` — the regime engine is upstream.
