# Project Japan — JEPX Storage Analytics

**[Live Dashboard]([projectjapan.vercel.app](https://projectjapan.vercel.app/))**

A power-market analytics platform for Japan: how much is an hour of cheap solar at noon worth to a battery in Tokyo? How much will a pumped-hydro plant in Hokkaido earn over the next year? What does the supply curve actually look like when 70% of the kerosene plants are offline for maintenance?

This repository answers those questions with a live dashboard, probabilistic price forecasts, and a Monte-Carlo valuation engine for grid-scale storage.

---

## The problem

Japan's electricity market is the second-largest in the OECD, deregulated in 2016, and split into nine interconnected utility regions trading half-hourly on the **Japan Electric Power Exchange (JEPX)**. Prices swing from below zero on sunny Kyushu afternoons to ¥80/kWh during a Tokyo cold snap.

Anyone holding a battery, a pumped-hydro plant, or any other form of energy storage faces the same question: *what is this asset actually worth, given how prices are likely to behave?* The honest answer is a distribution, not a number — and computing that distribution requires three things working together:

1. A model of what prices *should* be, from generator costs and demand. (Fundamentals.)
2. A model of how prices *will* be, with all the noise and weather and outages. (Forecast.)
3. A way to value optionality — the right to charge cheap and discharge expensive — over thousands of plausible futures. (Storage valuation.)

This project builds all three on top of a single Postgres database, hosted in Tokyo for low-latency access to Japanese data sources.

---

## What it does

The app has four surfaces, all sharing the same database:

### 1. Stack model — what the price *should* be
A merit-order supply curve built from generator-level marginal costs (fuel × heat-rate, plus carbon and O&M). Sort every plant by cost, stack them up to forecast demand, read off the marginal price. Run for each of the nine JEPX regions, every half-hour. Tells you whether today's market is rich, cheap, or in line with fundamentals.

### 2. VLSTM forecaster — what the price *will likely* be
A PyTorch LSTM with Monte-Carlo dropout that produces **1,000 plausible price paths × 48 half-hour slots × 9 regions** for the next 24 hours. Not a point forecast — paths preserve temporal correlation, so morning-spike-feeds-evening-spike behaviour survives the simulation. Updated twice daily from the latest demand, weather, and fuel prices.

### 3. LSM storage valuer — what your battery is worth
A Boogert & de Jong (2006) Least-Squares Monte-Carlo engine, adapted from gas-storage theory to batteries and pumped hydro. Feed it an asset spec (capacity, power rating, round-trip efficiency, cycle limit) and it consumes the 1,000 VLSTM paths to produce a value, a 90% confidence interval, an intrinsic vs. extrinsic split, and an optimal dispatch schedule.

Alongside it sits a **Basket of Spreads** valuation (Baker / O'Brien / Ogden / Strickland, *Risk* 2017) — the same problem solved as a portfolio of spread options, which is faster, more intuitive, and useful as a cross-check.

A **backtest engine** ties the three quant engines together so each new model release can be compared against actual market outcomes before going live.

---

## Live dashboard

The home page is a real cartographic map of Japan with the nine JEPX regions colour-coded by your choice of metric — share of renewables, supply/demand balance, or live JEPX clearing price. Click a region for the breakdown: demand, generation by fuel, current price, and a link straight into the stack-model inspector for that area.

Auto-refreshes every 30 minutes, with sub-second updates when new ingest data lands, via Supabase Realtime.

Other tabs cover the price forecast (fan chart with confidence bands), the stack curve (interactive: drag demand to see the marginal plant change), the regime panel (probability of "spike" / "drop" / "base" market state, from a Janczura-Weron Markov regime-switching model), and the strategy tab (BoS-derived optimal dispatch for a configurable BESS).

---

## Architecture

A Turborepo monorepo. The web app is **Next.js 14** (App Router, TypeScript) deployed to **Vercel** in Tokyo. The Python worker — ingest jobs, VLSTM training and inference, LSM engine, AI agent — runs on **Modal** in Tokyo. The database is **Supabase** Postgres in Tokyo, with Realtime channels feeding the dashboard live. Region-locked end to end because the page chains five or more dependent calls and every millisecond shows up. The only scheduler is Modal's `@app.function(schedule=...)` — no Airflow, no Prefect, no Redis. Postgres handles the half-hourly volume on its own.

---

## Repository layout

```
apps/web/             Next.js 14 dashboard + workbench + AI analyst UI
apps/worker/          Python: ingest, VLSTM, LSM, BoS, backtest, AI agent
packages/shared-types/  Postgres types shared between TS and Python
supabase/migrations/  Database schema, RLS policies, read-only agent role
```

Specifics: `apps/web/CLAUDE.md` documents the frontend conventions; `apps/worker/CLAUDE.md` covers the Python side; `BUILD_SPEC.md` is the source of truth for schema, units, and algorithm details across both.

---

## Local quickstart

Prerequisites: Node 20+, Python 3.11, [Modal CLI](https://modal.com/docs/guide), Docker (for local Supabase), [Supabase CLI](https://supabase.com/docs/guides/cli).

```bash
# 1. JS dependencies
npm install

# 2. Env templates — fill in your own Supabase / OpenAI / Modal values
cp .env.local.example .env.local
cp .env.example apps/worker/.env

# 3. Python worker
cd apps/worker
python3.11 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
cd ../..

# 4. Local Supabase (Docker)
supabase start
supabase db reset                              # applies migrations 001 → 005

# 5. Reference + dictionary seed
cd apps/worker
./.venv/bin/python -m seed.load_reference
./.venv/bin/python -m seed.load_data_dictionary
cd ../..

# 6. Run
npm run dev                                    # http://localhost:3000
```

---

## Status

The platform is feature-complete across ten milestones — data ingest, stack model, regime classifier, VLSTM forecaster, LSM valuer, backtest engine, AI analyst, dashboard, and production polish. Live regional ingest covers all nine utilities every half-hour; VLSTM forecasts refresh twice daily; storage valuations and backtests run on demand from the UI.

See `BUILD_SPEC.md` for the milestone sequence and gating criteria, and the `SESSION_LOG_*.md` files for a build diary.

---

## Why this exists

Most price-forecast and storage-valuation work that touches Japan sits inside private trading desks or consultancies. This project is an open, end-to-end implementation of the published methodology — stack models, MC-dropout LSTMs, Boogert-de Jong LSM, Basket of Spreads — applied to the real JEPX data feed. It exists partly as a working analytics tool, partly as a worked example of how the academic literature plugs into a live deregulated market.
