# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Currently between **Milestone 2 (database)** and **Milestone 3 (Tier 1 ingest)**. Migrations 001-003 + seed scripts + data dictionary YAML are written. Next milestone wires up the daily ingest jobs.

**Read `BUILD_SPEC.md` end-to-end before writing any code** — it is the source of truth for schema, algorithms, units, and milestone gating. The spec is non-negotiable on schema, units, and algorithm details; minor naming/structure choices may be decided locally.

## Product

JEPX-Storage — power-market analytics platform for the Japan Electric Power Exchange. Four surfaces over one Postgres DB:

1. **Stack model** — merit-order supply curve from generator-level SRMC × demand → fundamental clearing price per area.
2. **VLSTM forecaster** — PyTorch LSTM with MC Dropout producing 1000 price *paths* × 48 half-hour slots × 9 areas (not point forecasts; temporal correlation preserved).
3. **LSM storage valuer** — Boogert & de Jong (2006) Least-Squares Monte Carlo, adapted from gas storage to BESS / pumped hydro. Consumes VLSTM paths + asset spec → value, intrinsic/extrinsic split, CI, optimal dispatch.
4. **AI Analyst** — OpenAI SDK function-calling loop with read-only SQL access (via dedicated `agent_readonly` Postgres role + sqlglot SELECT-only parser), chart scratchpad, and on-demand what-if valuations. Every tool call audited.

A backtest engine ties the three quant engines together.

## Architecture (planned)

Turborepo monorepo:

- `apps/web/` — Next.js 14 App Router (TS strict), Tailwind + shadcn/ui, Recharts (standard) + Plotly (AI scratchpad), Zustand, TanStack Query v5. Deployed to Vercel `hnd1`. Server Components by default; Route Handlers under `src/app/api/` proxy to Modal endpoints; mutations via server actions. Realtime updates from Supabase (e.g. `valuations` row → frontend subscribes while Modal computes).
- `apps/worker/` — Python on Modal (Tokyo). `modal_app.py` is the entry. PyTorch + Lightning for VLSTM, NumPy + **Numba (`@jit(parallel=True)` mandatory)** for LSM, statsmodels `MarkovRegression` for the 3-regime Janczura-Weron MRS. FastAPI ASGI for the AI agent service. Modal `@app.function(schedule=...)` is the only scheduler — no Prefect/Airflow.
- `packages/shared-types/` — Postgres types generated for both TS and Python.
- `supabase/migrations/` — `001_init.sql` (schema), `002_rls.sql` (RLS), `003_agent_readonly_role.sql` (SELECT-only role for the agent).

Region-locked to Tokyo everywhere: Supabase `ap-northeast-1`, Vercel `hnd1`, Modal Tokyo workspace. Latency matters because page renders chain 5+ calls.

## Stack constraints (do not deviate without amending the spec)

Explicitly **not** in v1: TimescaleDB, DuckDB, Prefect/Airflow, Redis/Upstash, LangChain/LangGraph. Postgres alone handles the half-hourly volume; Modal scheduling covers cron; the agent uses the OpenAI SDK directly.

Validation at every boundary: **Pydantic** in Python, **zod** in TypeScript. No untyped data crosses a process boundary. Wrap every external call (OpenAI, Modal HTTP, Open-Meteo, japanesepower.org, frankfurter, CME) in try/except with audit logging to `compute_runs`.

## Critical gates

- **LSM engine:** `apps/worker/lsm/tests/test_boogert_dejong_replication.py` is the gate. If it fails, do not proceed to the backtest milestone. Numba JIT on the inner loop is mandatory — without `parallel=True` the engine is unusably slow.
- **VLSTM:** must beat naive ARIMA at 24h horizon on ≥6 of 9 areas before shipping the forecast UI.
- **Stack model:** RMSE < ¥3/kWh vs realised JEPX price on routine slots.
- **Agent SQL safety:** two independent layers — sqlglot parser rejects non-SELECT/WITH; `agent_readonly` Postgres role rejects writes regardless. Both must be verified.

## Milestone discipline

Spec §12 defines 10 sequential milestones, each ending in **STOP** — commit with a descriptive message naming the milestone, tell the operator exactly how to verify, wait for confirmation before continuing. Never blast through.

## Environment

Keys are pre-populated by the operator in `.env.local` (Next.js, repo root) and `apps/worker/.env` (also mirrored as Modal Secrets). Full list in spec §3. Never hardcode keys.

## Commands

- `npm run dev` — Turborepo; Next.js dev server at http://localhost:3000.
- `npm run worker:modal -- deploy modal_app.py` — Modal deploy using **Python 3.11** from `apps/worker/.venv` (run after `cd apps/worker && pip install -e ".[dev]"` into that venv). Equivalent health check: `npm run worker:modal -- run modal_app.py::healthcheck`.
- Optional worker tooling (same venv): `npm run worker:fmt`, `npm run worker:lint`, `npm run worker:mypy`.
