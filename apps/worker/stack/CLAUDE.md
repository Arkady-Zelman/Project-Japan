# apps/worker/stack — Claude Code context

The merit-order stack model. Consumes generators + fuel_prices + fx + weather + (optional) generation_mix actuals, produces `stack_curves` and `stack_clearing_prices`. See BUILD_SPEC §7.3 for the algorithm and §12 M4 for the RMSE gate.

## Modules

| File | Purpose |
| --- | --- |
| `models.py` | Pydantic for `Generator` (matches `generators` table), `StackCurveStep`, `StackClearingRow`. |
| `srmc.py` | SRMC formula + unit conversions ($/MMBtu × FX → ¥/MWh). Carbon price hardcoded — Japan has no compliance market in v1. |
| `weather_proxy.py` | Solar/wind output estimation from `weather_obs` for slots where `generation_mix_actuals` is missing. Used in 4 areas (CB, KS, CG, KY) post-2024-04 and intermittently elsewhere. |
| `generators_seed.yaml` | Hand-curated dispatchable fleet ~50-60 units across 9 areas. Public-knowledge sourced; verify against METI/utility data before bidding decisions in production. |
| `load_generators.py` | UPSERT loader: `python -m stack.load_generators`. Idempotent. |
| `build_curve.py` | Main engine. `build_for_slot(area, slot)` and `build_window(start, end)`. UPSERT to `stack_curves` + `stack_clearing_prices`. Cache via `inputs_hash` so re-runs skip unchanged slots. |
| `backtest.py` | RMSE/MAE/MAPE harness. CLI: `python -m stack.backtest --start ... --end ... [--area TK]`. |

## Discipline

- **Use `common.db.connect()`** everywhere — same rule as ingest.
- **Wrap stack runs in `compute_run("stack_build")`** so the dashboard sees them.
- **Per-area `advisory_lock(cur, "stack_<area>")`** — a backfill that re-runs the same area twice corrupts audit, and the build is cheap so locking is fine.
- **Generator efficiencies are public-knowledge approximations.** Don't treat them as authoritative. The `generators_seed.yaml` header lists sources + confidence flags. If a real bid book becomes available, replace the YAML wholesale.
- **Fuel-cycle costs (nuclear) live in `srmc.py` as constants**, not in `fuel_prices`. Uranium prices barely move at this resolution.

## Don't

- Don't add a separate hourly cache layer; `inputs_hash` in `stack_curves` already does this.
- Don't write to `generation_mix_actuals` from this directory — that's an ingest concern.
- Don't import from `vlstm/`, `regime/`, `lsm/` — the stack engine is upstream of all three.
