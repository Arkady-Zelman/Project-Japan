# apps/worker/lsm — Claude Code context

Boogert & de Jong (2006) Least-Squares Monte Carlo for storage valuation,
adapted from gas storage to battery energy storage systems (BESS) and
pumped hydro per BUILD_SPEC §8.

The engine is the most algorithmically critical artefact in the project —
M8 backtest and M9 AI Analyst both depend on it producing correct numbers.
The Boogert-de Jong replication test (`tests/test_boogert_dejong_replication.py`)
is the **non-negotiable STOP gate**: the engine must reproduce paper
Table 2 P3 within ±1% (5,447,010–5,557,136 EUR) before this directory's
output is trusted anywhere downstream.

Outputs:
- One row per valuation in `valuations` (status='done', total/intrinsic/
  extrinsic/CI columns populated).
- 48 rows per valuation in `valuation_decisions` (one per slot, mean SoC +
  most-common action + expected p&l).

Consumers:
- `/workbench` UI consumes `valuations` + `valuation_decisions` via Realtime.
- M8 backtest reuses `lsm.engine.run_lsm` directly to replay strategies.
- M9 AI Analyst calls the Modal HTTP endpoint for what-if valuations.

## Modules

| File | Purpose |
| --- | --- |
| `models.py` | Pydantic schemas: `AssetSpec`, `ValuationResult`. |
| `schwartz.py` | Schwartz 1-factor mean-reverting price simulator. Used by the gate test (paper §3.2 setup); reusable for synthetic-path mode if production ever grows beyond 48-slot horizons. |
| `engine.py` | The LSM. Two Numba `@njit(parallel=True)` kernels: `_backward_sweep` (OLS regression per (slot, volume grid point)) and `_forward_sweep` (path-level optimal action + cash accumulation). Pure-Python `run_lsm` wraps them. |
| `runner.py` | Production orchestration: load `forecast_paths`, build paths matrix, call `engine.run_lsm`, atomically persist `valuations` + `valuation_decisions` rows. Wraps in `compute_run("lsm_valuation")`. |
| `tests/test_boogert_dejong_replication.py` | The gate. Paper Table 2 P3 within ±1%. |

## Discipline

- **Numba `@njit(parallel=True)` is mandatory** on the inner kernels (BUILD_SPEC §8 line 1335). Without it the engine is unusably slow — pure-Python backward induction over (M=1000, N=51, T=48) takes 30+ minutes vs the <60s perf gate. Use `numba.prange` for the parallel loop axis. All kernel arguments must be plain ndarrays — no Pydantic, no pandas.
- **Use `common.db.connect()`** in `runner.py` — same rule as ingest + stack + regime + vlstm.
- **Wrap valuation runs in `compute_run("lsm_valuation")`** so the dashboard sees them.
- **Per-valuation `advisory_lock(cur, f"lsm_{valuation_id}")`** — concurrent retries on the same valuation race on the UPSERT.
- **Atomic `valuations` + `valuation_decisions` write**: status update + decision rows in one transaction so a partial failure leaves status='failed' rather than a half-populated decision set.
- **OLS basis matrix conditioning matters.** For the polynomial basis (1, S, S², S³), prices vary by ~10x across the gate test window which makes (X^T X) ill-conditioned. Center prices on the path-mean and rescale by the path-stdev before fitting. Equivalent fit, much better numerics.
- **Volume grid resolution**: N=51 by default. Paper uses 101 but profiling shows N=51 vs N=101 differs by <0.5% on the gate test — twice as fast, well within the ±1% tolerance.

## Don't

- Don't reach into the `assets` table from inside the Numba kernel — the kernel is pure ndarray. Pull asset spec into ndarray inputs in `run_lsm`.
- Don't autoregressively iterate the LSM (compute action at t, then re-run backward sweep to re-evaluate). Once-and-done backward sweep + forward sweep is the entire algorithm.
- Don't add a terminal-SoC penalty for v1 (BUILD_SPEC §8.1 explicitly defers; BESS has no required end-state).
- Don't import from `agent/` — LSM is upstream.
