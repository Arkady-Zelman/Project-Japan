# apps/worker — Claude Code context

Python 3.11 worker running on Modal (Tokyo workspace). Entry point: `modal_app.py`. `@app.function(schedule=...)` is the only scheduler — no Prefect/Airflow.

See `BUILD_SPEC.md`:
- §7 — ingest pipeline (sources, schedules, idempotency requirements)
- §8 — LSM engine spec (Boogert & de Jong replication, Numba `parallel=True` mandatory)
- §9 — AI agent spec (FastAPI ASGI, OpenAI function-calling loop, sqlglot SELECT-only parser, `agent_readonly` Postgres role)
- §11 — compute orchestration

## Conventions

- **Python 3.11 locally.** Use `apps/worker/.venv` (create with `python3.11 -m venv .venv` then `pip install -e ".[dev]"`). The workspace `.vscode/settings.json` pins the interpreter; from the repo root, `npm run worker:modal -- …` runs the Modal CLI with that venv.
- **Pydantic at every boundary.** No untyped data crosses a process boundary — DB fetch, HTTP response, tool input.
- **Wrap every external call** (OpenAI, Modal HTTP, Open-Meteo, japanesepower.org, **frankfurter** for FX, CME) in try/except with audit logging to the `compute_runs` table (table arrives in M2).
- **Idempotent UPSERT** on every ingest write — same input must produce same DB state when replayed.
- **`@jit(parallel=True)`** is mandatory on the LSM inner loop. Without it the engine is unusably slow per the spec's perf gate.
- **AI agent uses the OpenAI SDK** with function-calling, not Anthropic. Env var: `OPENAI_API_KEY`. Token budget 128k.
- **FX provider is frankfurter** (`https://api.frankfurter.dev`) — not exchangerate.host. Free, ECB-sourced.

## Layout

```
ingest/    M3 — Tier 1 ingest jobs (jepx, demand, generation_mix, weather, fx, holidays)
stack/     M4 — merit-order curve build + clearing
regime/    M5 — 3-regime Janczura-Weron MRS calibration
vlstm/     M6 — PyTorch Lightning forecaster with MC Dropout
lsm/       M7 — Numba LSM engine + Boogert-de Jong replication test (gate)
backtest/  M8 — strategy replay + slippage
agent/     M9 — FastAPI service + OpenAI tool-use loop
seed/      M2 — reference data + data dictionary loaders
```

## Schema discipline (post-M2)

- The DB schema lives in `supabase/migrations/`. Treat it as read-only from this directory — column changes go in a new migration file (`004_*.sql`, `005_*.sql`, …), never edited in place once applied.
- `seed/data_dictionary.yaml` must stay in lockstep with the schema. **Every column added to a migration requires a matching dictionary entry in the same change.** Re-run `python -m seed.load_data_dictionary` after editing.
- `seed/models.py` defines Pydantic mirrors only for tables this directory writes (areas, fuel_types, unit_types, jp_holidays, data_dictionary). Models for ingest/forecast/valuation tables live alongside their producers (e.g. `ingest/models.py`, etc.) at the milestone they're built.

## Ingest discipline (post-M3)

- **Use `common.db.connect()` everywhere.** Direct `psycopg.connect()` will eventually trip on the Supabase pooler — `prepare_threshold=None` is set in one place only.
- **Wrap the work in `compute_run("ingest_<source>")`** from `common.audit`. The dashboard reads `compute_runs` to surface ingest health; missing rows = blind operator.
- **Acquire `advisory_lock(cur, "ingest_<source>")`** inside the same transaction as the UPSERT. Concurrent runs of the same source corrupt audit accounting.
- **Decorate upstream HTTP calls with `@retry_transient`** (from `common.retry`). Don't decorate the entire `ingest()` — re-running writes after a partial success creates phantom audit rows.
- **Per-source dialects:** `generation_mix.py` shows the pattern for dual URL formats (TEPCO has annual + monthly publications with different schemas). The other 8 utilities have similar two-tier publications; rolling them out is mechanical — set `_AREA_SOURCES["XX"].implemented = True`, confirm the URL/encoding/header conventions, and the same parser shells should work.
- **Stale-source detection:** dynamic, not hardcoded. `demand.py::_upstream_latest()` is the template — read max(date) from the upstream and let `compute_runs.notes` say what's actually fresh. Hardcoded cutoffs go stale faster than the source.

## Stack engine discipline (post-M4)

- **Generator master is hand-curated.** `stack/generators_seed.yaml` covers ~73 dispatchable units (thermal + nuclear + pumped storage + 9 hydro aggregates) across 9 areas. Capacities are nameplate; efficiencies are literature defaults per (fuel, unit_type), not unit-specific. Replace wholesale if/when an Argus/OCCTO bid book becomes available.
- **`_DEFAULT_AVAILABILITY` in `stack/build_curve.py` is approximate** until `generator_availability` is populated. Nuclear at 0.30 is fleet-wide; a per-area override would tighten the model (TK 0%, KY ~0.5, KS ~0.4 reflect reality better).
- **Carbon price = ¥0/t** in `stack/srmc.py`. Lift to a constant or table when GX-ETS Phase 2 mandatory pricing activates.
- **Bulk-fetch pattern is mandatory.** `stack/build_curve.py::_load_area_cache` does one query per (area, input table). Per-slot DB queries inside the build loop will time out the Tokyo pooler — see SESSION_LOG_2026-05-06 for the diagnostic trail.
- **UPSERT via `cur.executemany` + `ON CONFLICT (area_id, slot_start) DO UPDATE`.** Two round-trips per chunk, regardless of chunk size.

## Milestone status

- M3: Six daily Modal cron ingest jobs live (jepx_prices, demand, generation_mix, weather, fx, holidays).
- M4 Phase 0: 5-utility per-utility CSV scraper rolled out (TK, HK, TH, HR, SK). 4 utilities (CB, KS, CG, KY) deferred per BUILD_SPEC §7.1.1.
- M4 Phase 1: `ingest_fuel_prices` shipped via FRED CSV mirrors (JKM, Newcastle, Brent). CME-direct deferred.
- M4 Phase 2-4: Stack engine populated (~73 generators, build_curve.py, backtest harness). RMSE on TK 2023-2024-Q1 = ¥5.3/kWh — gate is ¥3/kWh, FAILS structurally; see SESSION_LOG_2026-05-06 for diagnostic and three options.
- M4 Phase 5: shadcn/ui installed; `/dashboard` Section C (StackInspector) renders.

## Don't

- Don't read `.env` from the assistant. Operator populates it; secrets are off-limits to the assistant transcript.
- Don't add Prefect, Airflow, Celery, or any external scheduler — Modal's `@app.function(schedule=...)` covers v1.
- Don't add LangChain or LangGraph. Direct OpenAI SDK only.
- Don't replace Numba with pure NumPy in the LSM hot loop. The spec's perf gate depends on `parallel=True`.
