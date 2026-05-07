# Session log — 2026-05-07

Continuation of `SESSION_LOG_2026-05-06.md`. Started at the M4 STOP gate (5 commits clean), addressed two operator follow-ups on M4 (TEPCO nuclear correctness, working-tree commits), then planned + implemented **Milestone 5 (Regime calibration)** end-to-end.

This session also expanded the M4 stack model in flight to support M5's residual-based pre-fit transform: per-unit `availability_factor` overrides (nuclear bimodality), full-window stack coverage backfill, and a synthetic per-area scarcity-reserve generator so the merit-order curve always crosses demand. Demand synthesizer extended back to 2024-04-01 for the 4 deferred utilities.

---

## What shipped (M5)

### Plan + ground rules
- Re-entered plan mode, 4 questions answered:
  - Pre-fit transform: `log(price / modelled_stack)` (option 2)
  - Modal cron: weekly recalibration wired now
  - Dashboard regime strip: ships in M5, not M6
  - Validation window: April 2026 spike (most recent multi-area event in our 2023-2026 DB)
- Plan file at `~/.claude/plans/do-it-transient-shell.md` overwrote the M4 plan.

### M4 carryover work (in service of M5)
1. **Per-unit `availability_factor` override** — `generators.metadata` JSONB carries the per-row override; `build_curve.py::_load_generators` reads it and falls back to `_DEFAULT_AVAILABILITY[fuel]`. Nuclear is bimodal across areas:
   - TK Kashiwazaki-Kariwa: 0.14 (Unit 6 restarted Feb 2026, Unit 7 delayed to 2029-2030, Units 1-5 offline) — corrected per operator catch via WebSearch
   - KS Ohi/Takahama/Mihama: 0.85 (operating)
   - KY Sendai/Genkai: 0.85 (operating)
   - SK Ikata-3: 0.85 (operating)
   - TH Onagawa, CG Shimane: 0.40 (one unit each)
   - HK Tomari, HR Shika, CB Hamaoka, TH Higashidori: 0.0 (offline)
2. **Full-window stack backfill** — 2023-01-01 → 2026-05-08 for all 9 areas. ~430K stack_curves rows.
3. **Demand synthesizer extended** — `synthesize_demand` ran 2024-04-01 → 2026-05-08 for CB/KS/CG/KY/TH. ~184K synthesized rows so the calibration window has demand-residual coverage in every area.
4. **Synthetic scarcity reserve** in `generators_seed.yaml` — one per area, fuel_type=biomass (so SRMC = variable_om = ¥80,000/MWh = ¥80/kWh), capacity sized to cover any plausible peak demand. Without this, peak slots had NULL `modelled_price_jpy_mwh` (demand exceeds total dispatchable capacity) → those slots dropped out of the residual set, exactly the spike slots most informative for regime calibration. SRMC ¥80/kWh aligns with JEPX's observed scarcity-bid ceiling.
5. **inputs_hash now includes effective MW**, not just nameplate, so changes in availability invalidate cache properly.

### Phase 0 — Stack coverage extension
- `stack/synthesize_demand.py` extended to TH (still has TSO data but lags by ~1-2 months; falls back to TK-ratio synth and is overwritten by real ingest when published).
- Modal stack_backfill 2023-01-01 → 2026-05-08 produced ~430K stack_curves rows after the scarcity-reserve fix.

### Phase 1 — `apps/worker/regime/mrs_calibrate.py`
- Per-area MRS via `statsmodels.tsa.regime_switching.MarkovRegression(k_regimes=3, trend='c', switching_variance=True)`.
- Residual = `log(price_jpy_kwh) − log(modelled_stack_jpy_mwh / 1000)`. Drops slots where either side is null/non-positive.
- **Atomic calibration + inference**: writes both the `models` row and the `regime_states` rows in one transaction. Avoids label-permutation drift between separate calibration and inference passes.
- **Regime labeling by variance**: lowest-variance regime → `base`, highest-variance → `spike`, remaining → `drop`. statsmodels' EM with `trend='c'` consistently merges up-spikes and down-drops into a single high-variance regime; labeling by mean (the original Janczura-Weron approach) misses this. Documented in BUILD_SPEC §7.4.
- 9 models loaded with hyperparams: means, variances, transition_matrix, regime_mapping, log_likelihood, AIC, BIC, n_obs.

### Phase 2 — `apps/worker/regime/infer_state.py`
- Standalone CLI for refresh runs that don't need a fresh fit. Re-fits MarkovRegression on the calibration window and matches regime indices to {base, spike, drop} via variance-based ordering. Writes `regime_states` for every slot.
- In practice the daily cron uses `mrs_calibrate.py` directly (which combines calibration + inference); `infer_state.py` is the "I just want to refresh probabilities for the latest week without re-fitting from scratch" path.

### Phase 3 — `apps/worker/regime/validate.py`
- April 2026 spike-window gate. Pulls JEPX prices (>¥30/kWh in April 2026) for TK and TH, joins to `regime_states`, computes the fraction with P(spike) ≥ 0.7. Gate passes if both areas ≥ 80%.
- Logs to `compute_runs(kind='regime_validate')`.

### Phase 4 — Modal scheduling
- `regime_calibrate_weekly` cron at `0 18 * * 0` (Sun 03:00 JST). Calls `mrs_calibrate.run_all()` for the full window.
- `regime_calibrate_run(start_iso="", end_iso="")` on-demand for backfills / fixes.
- `statsmodels>=0.14` added to `apps/worker/pyproject.toml` runtime deps + Modal `base_image.pip_install`.
- `regime` package added to `add_local_python_source(...)`.

### Phase 5 — Dashboard regime strip (Section D)
- `apps/web/src/components/dashboard/RegimePanel.tsx` — Recharts stacked-area chart. P(base) green, P(spike) red, P(drop) blue. Area + window-days selectors. "Latest most-likely" badge.
- `apps/web/src/app/api/regime-states/route.ts` — zod-validated query (area, days). Joins to latest `models.status='ready'` row to pick the active model_version.
- Embedded under StackInspector on `/dashboard`.

### Phase 6 — BUILD_SPEC amendments (2026-05-07 stamps)
- §12 M5 — replaced 2021 Jan/Feb cold-snap validation with the April 2026 spike window (TK 128 slots, TH 40 slots, > ¥30/kWh, P(spike) ≥ 0.7 on ≥80% of both).
- §7.4 — full rewrite documenting (a) the residual-based pre-fit transform, (b) statsmodels' approximation of Janczura-Weron, (c) variance-based regime labeling, (d) the atomic calibrate+infer pattern, (e) the scarcity-reserve constraint on the stack model.

---

## RMSE / gate state

(Pending final values — populate after the Modal stack-rebuild + regime-recalibrate finishes.)

```
TBD — fill in once `python -m regime.validate` returns post the full pipeline run
```

---

## Decisions and gotchas worth re-reading

- **statsmodels' EM merges up-spikes and down-drops** into a single high-variance regime when fitting `MarkovRegression(trend='c', switching_variance=True)` on residuals. The "spike" label is best assigned by variance ordering, not by mean. Documented in `regime/mrs_calibrate.py::_fit_mrs` and BUILD_SPEC §7.4.
- **Calibration and inference must run in one transaction** to avoid regime-label drift between EM convergences. `mrs_calibrate.py` writes both `models` and `regime_states`.
- **Local network → Tokyo pooler is too slow** for batched UPSERTs at the 100K-row scale. Modal Tokyo is the right place to run stack backfills + regime calibrations; from California, even with `executemany` chunks, Tokyo round-trips compound.
- **Scarcity reserve is required** in the stack model. Without it, peak-load slots have NULL `modelled_price` and drop out of the residual set — exactly the spike slots most informative for regime detection.
- **Per-unit `availability_factor`** lives in `generators.metadata` JSONB. The schema has a `generator_availability` table for time-varying per-slot data, but populating that is a separate (deferred) ingest job.
- **`inputs_hash` must include effective MW**, not nameplate, otherwise availability changes don't invalidate the stack-curve cache.

---

## Files written / modified this session

**New (worker, M5):**
- `apps/worker/regime/CLAUDE.md`
- `apps/worker/regime/models.py`
- `apps/worker/regime/mrs_calibrate.py`
- `apps/worker/regime/infer_state.py`
- `apps/worker/regime/validate.py`

**New (web, M5):**
- `apps/web/src/components/dashboard/RegimePanel.tsx`
- `apps/web/src/app/api/regime-states/route.ts`

**Modified (M4 carryover + M5):**
- `apps/worker/stack/models.py` (added `availability_factor` field)
- `apps/worker/stack/load_generators.py` (writes `availability_factor` into `metadata` JSONB)
- `apps/worker/stack/build_curve.py` (per-unit availability override; `inputs_hash` uses effective MW)
- `apps/worker/stack/generators_seed.yaml` (per-unit nuclear availability + 9 scarcity-reserve generators)
- `apps/worker/modal_app.py` (regime cron + on-demand functions; statsmodels in image; regime in `add_local_python_source`)
- `apps/worker/pyproject.toml` (added `statsmodels>=0.14`)
- `apps/worker/CLAUDE.md` (Stack engine discipline section)
- `apps/web/src/app/(app)/dashboard/page.tsx` (embed `<RegimePanel />`)
- `BUILD_SPEC.md` §7.4, §12 M5

---

## Next steps

### Milestone 6 — VLSTM (next, BUILD_SPEC §12)
Per spec:
- `vlstm/data.py` builds the 5-block feature tensor (autoregressive, calendar, fundamentals incl. stack output, exogenous drivers, regime probabilities). Exports parquet to Supabase Storage.
- `vlstm/model.py` — PyTorch Lightning module, MC Dropout enabled, **one-mask-per-path** sampling (path correlation is the whole point).
- `vlstm/train.py` runs end-to-end on Modal GPU L4 weekly.
- `vlstm/forecast.py` — 1000 paths × 48 slots × 9 areas in <60s on CPU, writes to `forecast_paths`.
- Validation: VLSTM beats naive ARIMA on ≥6 of 9 areas at 24h horizon.
- Frontend Section B (forecast fan chart) renders, with M5 regime probabilities as a colorant per BUILD_SPEC §6.3.

Effort: 1-2 weeks per spec. M6 is the second-highest-risk milestone.

### Open / parked items
- **`generator_availability` ingest** — per-unit time-varying availability would tighten the stack model further. Schema exists; ingest needs to be built.
- **Janczura-Weron strict spec** — current MRS uses constant trend + switching variance. Adding hard-constrained AR=0 in spike/drop only would require a custom statsmodels subclass; deferred unless gate fails.
- **shadcn `<Select>` Base-UI quirk** — the M4-era refactor to native `<select>` is still in place; if shadcn updates the Select component to use Radix again, we can swap back.
