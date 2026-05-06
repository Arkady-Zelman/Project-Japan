# JEPX-Storage — Full Build Specification

**Read this entire document before writing any code. This is the complete source of truth for the build.**

---

## 1. Project overview

JEPX-Storage is a power market analytics platform for the Japan Electric Power Exchange (JEPX). It combines three quantitative engines and an AI analyst into a single product for power traders, BESS developers, structurers, and quant researchers operating on the Japanese market.

The three engines:

1. **Stack model** — a merit-order ("supply curve") model that reconstructs Japan's power supply curve for any 30-minute slot from generator-level fuel costs, efficiency, and availability, then crosses it with demand to produce a fundamental clearing price by area.

2. **VLSTM probabilistic forecaster** — an LSTM with Monte Carlo dropout that produces *price paths*, not point estimates. Its output is N (default 1000) plausible price paths over the next 48 half-hour slots per area, with realistic temporal correlation preserved.

3. **LSM storage valuer** — a direct implementation of Boogert & de Jong (2006) Least-Squares Monte Carlo, adapted from gas storage to battery energy storage systems (BESS) and pumped hydro. Consumes the VLSTM's price paths plus a user-defined asset spec and produces total value, intrinsic/extrinsic split, confidence interval, and an optimal slot-by-slot dispatch policy.

Plus a fourth surface: **AI Analyst tab** — a persistent chat with an OpenAI model that has read-only access to the platform's data, can run SQL, generate charts in a side scratchpad, run correlations and quick regressions, and trigger on-demand "what-if" valuations. Every tool call is audited.

Three core engines, one AI analyst, a backtest engine that ties them all together, all on top of one Postgres database.

This is a real product targeting a real market. The dataset is real JEPX data going back to 2015.

---

## 2. Tech stack (locked — do not deviate)

| Concern | Choice |
| --- | --- |
| Frontend framework | Next.js 14, App Router, TypeScript strict mode |
| Styling | Tailwind CSS + shadcn/ui (install via `npx shadcn@latest init`) |
| Frontend hosting | Vercel (Tokyo region — `hnd1`) |
| Charts (standard) | Recharts |
| Charts (AI scratchpad) | Plotly.js (rendered from JSON spec) |
| Client state | Zustand |
| Server cache | TanStack Query v5 |
| Database / Auth / Storage | Supabase (Postgres 15, region `ap-northeast-1`/Tokyo) |
| Heavy compute | Modal (Tokyo region) — Python, GPU-on-demand |
| ML framework | PyTorch + PyTorch Lightning |
| LSM engine | NumPy + Numba (JIT, `parallel=True`) |
| Regime model | `statsmodels.tsa.regime_switching.MarkovRegression` |
| Data ingest | Python + Pydantic (validation) |
| AI agent backend | FastAPI on Modal + OpenAI SDK (function-calling loop) |
| Browser automation (scraping) | Playwright |
| Forms (frontend) | react-hook-form + zod |
| LLM output validation | zod (TS) and Pydantic (Python) |
| Observability | Sentry (errors) + PostHog (product analytics) |
| CI | GitHub Actions + Vercel preview deployments |

Things explicitly **NOT** in the v1 stack (do not add unless the spec is amended):

- TimescaleDB / hypertables — Postgres handles tens of millions of half-hourly rows fine without it. Add only if query performance actually degrades.
- DuckDB — superseded by a Postgres `agent_readonly` role for the AI agent's safety.
- Prefect / Airflow — Modal's `@app.function(schedule=...)` covers all v1 cron needs.
- Upstash Redis / any external cache — Supabase + Vercel KV are sufficient.
- LangChain / LangGraph — the agent uses the OpenAI SDK directly.

> **Deferred 2026-04-30:** shadcn/ui install was attempted in M1 and rolled back. The current shadcn registry (`base-nova`, v4) targets Tailwind v4 and pulls in `@base-ui/react` + OKLCH color tokens, which broke against Tailwind v3.4 that `create-next-app@14` ships. M1 ended with no shadcn primitives installed and `apps/web` on Tailwind v3. Decision deferred to **M4** (`/workbench`) when Form/Dialog/Tabs/Tooltip primitives become load-bearing — at that point we either upgrade Tailwind v3 → v4 + install latest shadcn, pin shadcn to a v3-compatible release, or hand-roll. M3 (`/dashboard` ingest-status page) is hand-rolled with Tailwind utilities only.

---

## 3. Environment variables

All values will be pre-populated in `.env.local` (Next.js) and `.env` (Modal/Python) by the operator. **Do not hardcode any keys anywhere.**

```
# ============================================================
# Next.js (.env.local at repo root)
# ============================================================

# Supabase
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=

# Modal (compute backend) — used by Vercel server actions to call Modal HTTP endpoints
MODAL_LSM_ENDPOINT=
MODAL_FORECAST_ENDPOINT=
MODAL_AGENT_ENDPOINT=
MODAL_API_TOKEN=

# Sentry (frontend)
NEXT_PUBLIC_SENTRY_DSN=

# PostHog
NEXT_PUBLIC_POSTHOG_KEY=
NEXT_PUBLIC_POSTHOG_HOST=

# ============================================================
# Modal / Python workers (.env at apps/worker root, also set as Modal Secrets)
# ============================================================

# Supabase service role (full access for ingest workers)
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=

# Supabase agent_readonly role (used only by AI agent service)
SUPABASE_AGENT_READONLY_DB_URL=

# OpenAI (for AI agent)
OPENAI_API_KEY=

# Open-Meteo — no key required, but base URL is config
OPEN_METEO_BASE_URL=https://archive-api.open-meteo.com/v1/archive
OPEN_METEO_FORECAST_URL=https://api.open-meteo.com/v1/forecast

# Frankfurter (ECB-sourced FX, no key required)
FRANKFURTER_BASE_URL=https://api.frankfurter.dev

# CME (delayed JKM/coal feeds — public endpoints, no key)
CME_BASE_URL=https://www.cmegroup.com

# japanesepower.org community hub (v1 ingest source)
JAPANESEPOWER_BASE_URL=https://japanesepower.org
```

Generate a `.env.local.example` and `.env.example` mirroring these (with empty values), commit both.

---

## 4. Repository structure

Monorepo layout via Turborepo.

```
jepx-storage/
├── BUILD_SPEC.md                  # this file — source of truth
├── README.md                      # you generate: setup + run instructions
├── CLAUDE.md                      # repo-root context for Claude Code
├── package.json                   # turbo workspace root
├── turbo.json
├── .env.local.example
├── .env.example
├── .gitignore
├── apps/
│   ├── web/                       # Next.js frontend
│   │   ├── src/
│   │   │   ├── app/
│   │   │   │   ├── layout.tsx
│   │   │   │   ├── page.tsx           # landing
│   │   │   │   ├── login/page.tsx
│   │   │   │   ├── (app)/             # authed routes
│   │   │   │   │   ├── dashboard/page.tsx     # market dashboard
│   │   │   │   │   ├── workbench/             # asset config & valuation
│   │   │   │   │   │   ├── page.tsx           # asset list
│   │   │   │   │   │   └── [assetId]/page.tsx
│   │   │   │   │   ├── lab/page.tsx           # strategy lab / backtests
│   │   │   │   │   └── analyst/page.tsx       # AI Analyst tab
│   │   │   │   └── api/
│   │   │   │       ├── value-asset/route.ts   # POST → kicks off Modal LSM
│   │   │   │       ├── backtest/route.ts
│   │   │   │       ├── refresh-forecast/route.ts
│   │   │   │       └── agent/route.ts         # POST → relays to Modal agent svc
│   │   │   ├── components/
│   │   │   │   ├── ui/                # shadcn primitives
│   │   │   │   ├── charts/            # recharts wrappers
│   │   │   │   ├── dashboard/
│   │   │   │   ├── workbench/
│   │   │   │   ├── lab/
│   │   │   │   └── analyst/           # chat UI + scratchpad
│   │   │   ├── hooks/
│   │   │   │   ├── useAssets.ts
│   │   │   │   ├── useValuationStream.ts
│   │   │   │   ├── useChatMessages.ts
│   │   │   │   └── useRealtimeForecast.ts
│   │   │   ├── lib/
│   │   │   │   ├── supabase/
│   │   │   │   │   ├── client.ts      # browser (anon key)
│   │   │   │   │   └── server.ts      # server (service role)
│   │   │   │   └── modal-client.ts    # typed wrappers around Modal endpoints
│   │   │   └── types/db.ts            # generated Supabase types
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── next.config.js
│   │   └── tailwind.config.ts
│   └── worker/                    # Python / Modal compute
│       ├── pyproject.toml
│       ├── modal_app.py           # Modal app entry
│       ├── CLAUDE.md              # subdir context
│       ├── ingest/
│       │   ├── jepx_prices.py
│       │   ├── generation_mix.py
│       │   ├── demand.py
│       │   ├── weather.py
│       │   ├── fuel_prices.py
│       │   ├── fx.py
│       │   ├── holidays.py
│       │   └── common.py          # idempotent UPSERT, retry, schemas
│       ├── stack/
│       │   ├── srmc.py            # SRMC = (fuel/eff) + vom + carbon
│       │   ├── build_curve.py
│       │   └── solve_clearing.py
│       ├── regime/
│       │   ├── mrs_calibrate.py   # 3-regime Janczura-Weron MRS
│       │   └── infer_state.py
│       ├── vlstm/
│       │   ├── data.py            # feature engineering + parquet export
│       │   ├── model.py           # PyTorch Lightning module
│       │   ├── train.py           # weekly retrain (Modal scheduled)
│       │   └── forecast.py        # daily inference (Modal scheduled)
│       ├── lsm/
│       │   ├── engine.py          # Numba-accelerated core
│       │   ├── basis.py           # basis functions
│       │   ├── intrinsic.py       # baseline strategies
│       │   └── tests/
│       │       └── test_boogert_dejong_replication.py
│       ├── backtest/
│       │   ├── runner.py
│       │   └── slippage.py
│       └── agent/
│           ├── service.py         # FastAPI app (Modal HTTP endpoint)
│           ├── tools.py           # query_data, create_chart, etc.
│           └── prompts.py
├── packages/
│   └── shared-types/              # generated Postgres types shared TS↔Python
│       ├── src/index.ts
│       └── package.json
└── supabase/
    └── migrations/
        ├── 001_init.sql           # full schema
        ├── 002_rls.sql            # row-level security policies
        └── 003_agent_readonly_role.sql  # SELECT-only role for AI agent
```

---

## 5. Database schema

Place in `supabase/migrations/001_init.sql`. Operator pastes into Supabase SQL editor.

```sql
-- ============================================================
-- EXTENSIONS
-- ============================================================
create extension if not exists "uuid-ossp";
create extension if not exists "pg_stat_statements";

-- ============================================================
-- REFERENCE DATA (slow-changing, seed at install time)
-- ============================================================

create table areas (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,           -- 'TK','KS','HK','TH','CB','HR','CG','SK','KY','SYS'
  name_en text not null,
  name_jp text,
  tso text,
  timezone text default 'Asia/Tokyo'
);

create table fuel_types (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,           -- 'lng_ccgt','lng_steam','coal','oil','nuclear','solar','wind','hydro','geothermal','biomass','pumped_storage','battery'
  name_en text not null
);

create table unit_types (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  name_en text not null
);

create table jp_holidays (
  date date primary key,
  name_jp text,
  name_en text,
  category text                        -- 'national' | 'obon' | 'newyear' | 'goldenweek'
);

-- ============================================================
-- MARKET DATA (time-series, append-only from ingest workers)
-- ============================================================

create table jepx_spot_prices (
  id bigserial primary key,
  area_id uuid not null references areas(id),
  slot_start timestamptz not null,
  slot_end timestamptz not null,
  price_jpy_kwh numeric(10,4),
  sell_volume_mwh numeric(12,2),
  buy_volume_mwh numeric(12,2),
  contract_volume_mwh numeric(12,2),
  auction_type text not null check (auction_type in ('day_ahead','intraday')),
  source text not null,                -- 'japanesepower_csv' | 'jepx_csv' | 'eex' | 'ice'
  ingested_at timestamptz default now(),
  unique (area_id, slot_start, auction_type)
);
create index on jepx_spot_prices (slot_start desc);
create index on jepx_spot_prices (area_id, slot_start desc);

create table demand_actuals (
  area_id uuid not null references areas(id),
  slot_start timestamptz not null,
  demand_mw numeric(12,2),
  source text not null,
  ingested_at timestamptz default now(),
  primary key (area_id, slot_start)
);
create index on demand_actuals (slot_start desc);

create table generation_mix_actuals (
  area_id uuid not null references areas(id),
  slot_start timestamptz not null,
  fuel_type_id uuid not null references fuel_types(id),
  output_mw numeric(12,2),
  curtailment_mw numeric(12,2),
  source text not null,
  ingested_at timestamptz default now(),
  primary key (area_id, slot_start, fuel_type_id)
);
create index on generation_mix_actuals (slot_start desc);

create table interconnection_flows (
  from_area_id uuid not null references areas(id),
  to_area_id uuid not null references areas(id),
  slot_start timestamptz not null,
  flow_mw numeric(10,2),               -- positive = from→to
  source text default 'occto',
  ingested_at timestamptz default now(),
  primary key (from_area_id, to_area_id, slot_start)
);

create table generators (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  operator text,
  area_id uuid not null references areas(id),
  unit_type_id uuid references unit_types(id),
  fuel_type_id uuid not null references fuel_types(id),
  capacity_mw numeric(10,2) not null,
  efficiency numeric(5,4),             -- HHV thermal efficiency, e.g. 0.58
  heat_rate_kj_kwh numeric(8,2),
  variable_om_jpy_mwh numeric(10,2),
  co2_intensity_t_mwh numeric(6,4),
  commissioned date,
  retired date,
  notes text,
  metadata jsonb default '{}'
);

create table generator_availability (
  generator_id uuid not null references generators(id) on delete cascade,
  slot_start timestamptz not null,
  available_mw numeric(10,2),
  status text check (status in ('available','planned_outage','forced_outage','derated')),
  source text,
  primary key (generator_id, slot_start)
);

create table fuel_prices (
  fuel_type_id uuid not null references fuel_types(id),
  ts timestamptz not null,
  price numeric(12,4) not null,
  unit text not null,                  -- 'usd_mmbtu' | 'usd_t' | 'usd_bbl'
  source text not null,
  ingested_at timestamptz default now(),
  primary key (fuel_type_id, ts, source)
);

create table fx_rates (
  pair text not null,                  -- 'USDJPY'
  ts timestamptz not null,
  rate numeric(12,6) not null,
  source text not null,
  primary key (pair, ts, source)
);

create table weather_obs (
  area_id uuid not null references areas(id),
  ts timestamptz not null,
  temp_c numeric(5,2),
  dewpoint_c numeric(5,2),
  wind_mps numeric(5,2),
  ghi_w_m2 numeric(7,2),
  cloud_pct numeric(5,2),
  forecast_horizon_h smallint not null default 0,
  source text not null,
  primary key (area_id, ts, forecast_horizon_h, source)
);

-- ============================================================
-- FUNDAMENTALS (derived from market data + stack model)
-- ============================================================

create table stack_curves (
  id uuid primary key default gen_random_uuid(),
  area_id uuid not null references areas(id),
  slot_start timestamptz not null,
  curve_jsonb jsonb not null,          -- [{mw_cumulative, srmc_jpy_mwh, generator_id}, ...]
  inputs_hash text not null,           -- hash of fuel/availability inputs
  created_at timestamptz default now(),
  unique (area_id, slot_start)
);
create index on stack_curves (area_id, slot_start desc);

create table stack_clearing_prices (
  area_id uuid not null references areas(id),
  slot_start timestamptz not null,
  modelled_price_jpy_mwh numeric(10,4),
  modelled_demand_mw numeric(12,2),
  marginal_unit_id uuid references generators(id),
  stack_curve_id uuid references stack_curves(id),
  created_at timestamptz default now(),
  primary key (area_id, slot_start)
);

-- ============================================================
-- REGIME STATE
-- ============================================================

create table regime_states (
  area_id uuid not null references areas(id),
  slot_start timestamptz not null,
  p_base numeric(6,5) not null,
  p_spike numeric(6,5) not null,
  p_drop numeric(6,5) not null,
  most_likely_regime text not null check (most_likely_regime in ('base','spike','drop')),
  model_version text not null,
  primary key (area_id, slot_start, model_version)
);

-- ============================================================
-- MODELS & FORECASTS
-- ============================================================

create table models (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  type text not null check (type in ('vlstm','arima','stack','mrs','ensemble')),
  version text not null,
  hyperparams jsonb default '{}',
  training_window_start timestamptz,
  training_window_end timestamptz,
  metrics jsonb default '{}',          -- RMSE, MAPE, CRPS, by area & horizon
  artifact_url text,                   -- Supabase Storage path
  status text not null default 'training' check (status in ('training','ready','deprecated','failed')),
  created_at timestamptz default now(),
  unique (name, version)
);

create table forecast_runs (
  id uuid primary key default gen_random_uuid(),
  model_id uuid not null references models(id),
  area_id uuid not null references areas(id),
  forecast_origin timestamptz not null,
  horizon_slots int not null,
  n_paths int not null,
  created_at timestamptz default now()
);
create index on forecast_runs (area_id, forecast_origin desc);

create table forecast_paths (
  forecast_run_id uuid not null references forecast_runs(id) on delete cascade,
  path_id int not null,
  slot_start timestamptz not null,
  price_jpy_kwh numeric(10,4) not null,
  primary key (forecast_run_id, path_id, slot_start)
);
create index on forecast_paths (forecast_run_id, slot_start);

-- ============================================================
-- USER & ASSET STATE (RLS-protected)
-- ============================================================

create table portfolios (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  description text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table assets (
  id uuid primary key default gen_random_uuid(),
  portfolio_id uuid not null references portfolios(id) on delete cascade,
  user_id uuid not null references auth.users(id),  -- denormalised for RLS
  name text not null,
  asset_type text not null check (asset_type in ('bess_li_ion','pumped_hydro','compressed_air')),
  area_id uuid not null references areas(id),
  power_mw numeric(10,2) not null,
  energy_mwh numeric(12,2) not null,
  round_trip_eff numeric(4,3) not null,
  max_cycles_per_year numeric(6,2),
  degradation_jpy_mwh numeric(10,2) default 0,
  soc_min_pct numeric(4,3) default 0.10,
  soc_max_pct numeric(4,3) default 0.95,
  commissioned date,
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

create table valuations (
  id uuid primary key default gen_random_uuid(),
  asset_id uuid not null references assets(id) on delete cascade,
  user_id uuid not null references auth.users(id),
  forecast_run_id uuid references forecast_runs(id),
  method text not null check (method in ('lsm','intrinsic','rolling_intrinsic')),
  status text not null default 'queued' check (status in ('queued','running','done','failed')),
  horizon_start timestamptz not null,
  horizon_end timestamptz not null,
  intrinsic_value_jpy numeric(15,2),
  extrinsic_value_jpy numeric(15,2),
  total_value_jpy numeric(15,2),
  ci_lower_jpy numeric(15,2),
  ci_upper_jpy numeric(15,2),
  basis_functions jsonb,
  n_paths int,
  n_volume_grid int,
  runtime_seconds numeric(8,2),
  error text,
  created_at timestamptz default now(),
  completed_at timestamptz
);
create index on valuations (asset_id, created_at desc);

create table valuation_decisions (
  valuation_id uuid not null references valuations(id) on delete cascade,
  slot_start timestamptz not null,
  soc_mwh numeric(12,2),
  action_mw numeric(10,2),             -- + = charge, - = discharge
  expected_pnl_jpy numeric(12,2),
  primary key (valuation_id, slot_start)
);

create table backtests (
  id uuid primary key default gen_random_uuid(),
  asset_id uuid not null references assets(id) on delete cascade,
  user_id uuid not null references auth.users(id),
  model_id uuid references models(id),
  strategy text not null check (strategy in ('lsm','intrinsic','rolling_intrinsic','naive_spread')),
  window_start date not null,
  window_end date not null,
  status text not null default 'queued' check (status in ('queued','running','done','failed')),
  realised_pnl_jpy numeric(15,2),
  modelled_pnl_jpy numeric(15,2),
  slippage_jpy numeric(15,2),
  sharpe numeric(6,3),
  max_drawdown_jpy numeric(15,2),
  trades_jsonb jsonb,
  error text,
  created_at timestamptz default now(),
  completed_at timestamptz
);

-- ============================================================
-- AI AGENT STATE
-- ============================================================

create table chat_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text,
  created_at timestamptz default now()
);

create table chat_messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references chat_sessions(id) on delete cascade,
  role text not null check (role in ('user','assistant','tool')),
  content text not null,
  tool_calls jsonb default '[]',
  tool_results jsonb default '[]',
  tokens_in int,
  tokens_out int,
  created_at timestamptz default now()
);
create index on chat_messages (session_id, created_at);

create table agent_artifacts (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references chat_sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id),
  type text not null check (type in ('chart','query_result','model_spec')),
  title text,
  spec_jsonb jsonb not null,
  created_at timestamptz default now(),
  expires_at timestamptz default (now() + interval '7 days'),
  pinned boolean default false
);
create index on agent_artifacts (session_id, created_at);

-- ============================================================
-- DATA DICTIONARY (read by AI agent system prompt at runtime)
-- ============================================================

create table data_dictionary (
  table_name text not null,
  column_name text not null,
  description text not null,
  unit text,
  notes text,
  primary key (table_name, column_name)
);

-- ============================================================
-- AUDIT LOG (every Modal compute run + every agent tool call)
-- ============================================================

create table compute_runs (
  id uuid primary key default gen_random_uuid(),
  kind text not null,                  -- 'lsm_valuation' | 'forecast_inference' | 'vlstm_train' | 'mrs_calibrate' | 'agent_tool_call' | 'ingest_jepx' | ...
  user_id uuid references auth.users(id),
  input jsonb,
  output jsonb,
  status text not null check (status in ('queued','running','done','failed')),
  duration_ms int,
  error text,
  created_at timestamptz default now()
);
create index on compute_runs (created_at desc);
create index on compute_runs (kind, created_at desc);
```

### 5.2 RLS — `supabase/migrations/002_rls.sql`

```sql
-- Reference + market + fundamentals + models: read-only for authenticated users.
-- Write access is service-role only (used by Modal ingest workers).

alter table areas enable row level security;
alter table fuel_types enable row level security;
alter table unit_types enable row level security;
alter table jp_holidays enable row level security;
alter table jepx_spot_prices enable row level security;
alter table demand_actuals enable row level security;
alter table generation_mix_actuals enable row level security;
alter table interconnection_flows enable row level security;
alter table generators enable row level security;
alter table generator_availability enable row level security;
alter table fuel_prices enable row level security;
alter table fx_rates enable row level security;
alter table weather_obs enable row level security;
alter table stack_curves enable row level security;
alter table stack_clearing_prices enable row level security;
alter table regime_states enable row level security;
alter table models enable row level security;
alter table forecast_runs enable row level security;
alter table forecast_paths enable row level security;
alter table data_dictionary enable row level security;

-- Generic "authenticated read" policy for the above.
do $$
declare t text;
begin
  for t in
    select unnest(array[
      'areas','fuel_types','unit_types','jp_holidays',
      'jepx_spot_prices','demand_actuals','generation_mix_actuals','interconnection_flows',
      'generators','generator_availability','fuel_prices','fx_rates','weather_obs',
      'stack_curves','stack_clearing_prices','regime_states',
      'models','forecast_runs','forecast_paths','data_dictionary'
    ])
  loop
    execute format(
      'create policy "auth_read_%I" on %I for select to authenticated using (true);',
      t, t
    );
  end loop;
end$$;

-- User-scoped tables: users see only their own rows.
alter table portfolios enable row level security;
create policy "users_own_portfolios" on portfolios for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

alter table assets enable row level security;
create policy "users_own_assets" on assets for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

alter table valuations enable row level security;
create policy "users_own_valuations" on valuations for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

alter table valuation_decisions enable row level security;
create policy "users_own_valuation_decisions" on valuation_decisions for all
  using (
    valuation_id in (select id from valuations where user_id = auth.uid())
  );

alter table backtests enable row level security;
create policy "users_own_backtests" on backtests for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

alter table chat_sessions enable row level security;
create policy "users_own_chat_sessions" on chat_sessions for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

alter table chat_messages enable row level security;
create policy "users_own_chat_messages" on chat_messages for all
  using (
    session_id in (select id from chat_sessions where user_id = auth.uid())
  );

alter table agent_artifacts enable row level security;
create policy "users_own_artifacts" on agent_artifacts for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

alter table compute_runs enable row level security;
create policy "users_own_compute_runs" on compute_runs for select
  using (user_id = auth.uid() or user_id is null);
```

### 5.3 Agent read-only role — `supabase/migrations/003_agent_readonly_role.sql`

```sql
-- The AI agent connects to Postgres using this role. It physically cannot mutate data.
-- This is a defence-in-depth on top of "the agent backend only calls SELECT" — even if a
-- prompt-injection slips through, the database refuses writes.

create role agent_readonly nologin;

grant usage on schema public to agent_readonly;
grant select on all tables in schema public to agent_readonly;
alter default privileges in schema public grant select on tables to agent_readonly;

-- Create a login user that inherits agent_readonly. The password is set by the operator
-- in the Supabase dashboard (Database → Roles) and the connection string is stored in
-- SUPABASE_AGENT_READONLY_DB_URL.
create user agent_user with login in role agent_readonly;
-- Operator runs:  alter user agent_user with password '<set in dashboard>';

-- Belt-and-braces: explicitly revoke writes from the agent role on user-scoped tables.
revoke insert, update, delete on assets, portfolios, valuations, backtests,
       chat_sessions, chat_messages, agent_artifacts from agent_readonly;

-- ==========================================================
-- ADDED 2026-05-01 (post-M2 deviation from the original spec).
--
-- The "auth_read_*" policies in 002_rls.sql only target the `authenticated`
-- role. Without parallel policies for `agent_readonly`, the agent_user
-- connects fine, has table-level SELECT permission, but RLS filters every
-- row — agent sees zero rows in production. Caught during M2 cloud
-- verification on 2026-05-01. Mirror the §5.2 policy block for
-- agent_readonly on public market/reference/model tables only — agent
-- stays blind to user-scoped tables (assets, portfolios, valuations,
-- backtests, chat_sessions, chat_messages, agent_artifacts).
-- ==========================================================

do $$
declare t text;
begin
  for t in
    select unnest(array[
      'areas','fuel_types','unit_types','jp_holidays',
      'jepx_spot_prices','demand_actuals','generation_mix_actuals','interconnection_flows',
      'generators','generator_availability','fuel_prices','fx_rates','weather_obs',
      'stack_curves','stack_clearing_prices','regime_states',
      'models','forecast_runs','forecast_paths','data_dictionary'
    ])
  loop
    execute format(
      'create policy "agent_read_%I" on %I for select to agent_readonly using (true);',
      t, t
    );
  end loop;
end$$;
```

After running migrations, the README must instruct the operator to:

1. Set the `agent_user` password in Supabase Dashboard → Database → Roles, copy the resulting connection string into `SUPABASE_AGENT_READONLY_DB_URL`.
2. Enable Realtime on these tables (Dashboard → Database → Replication): `valuations`, `backtests`, `forecast_runs`, `chat_messages`, `agent_artifacts`, `compute_runs`.
3. Seed reference data (`areas`, `fuel_types`, `unit_types`, `jp_holidays`) by running `python apps/worker/seed/load_reference.py` — this is a one-time script that loads the 9 JEPX areas, ~12 fuel types, ~8 unit types, and 5 years of Japanese holidays.
4. Seed `data_dictionary` from a YAML file checked into the repo (`apps/worker/seed/data_dictionary.yaml`). Every new column added later must come with a dictionary entry — agent quality depends on it.

---

## 6. Routes and UI surfaces

### 6.1 `/` — Landing

Centred page: product name "JEPX-Storage", one-line tagline ("Stack model, probabilistic forecasts, and Boogert & de Jong storage valuation for Japan's power market"), primary CTA "Sign in".

### 6.2 `/login` — Auth

Supabase Auth UI: email/password and Google OAuth. On success, redirect to `/dashboard`.

### 6.3 `/dashboard` — Market dashboard

Default landing for authenticated users. Three sections, top-to-bottom:

**Section A — Live price strip.** Sparkline per area (9 areas + system) showing the last 48 slots of `jepx_spot_prices` with the current modelled clearing price overlaid. Click an area → drill-in to that area's full chart.

**Section B — Forecast panel.** For the selected area: a fan chart showing the latest forecast — point estimate (mean of paths) plus 5/25/75/95 percentile bands from `forecast_paths`. X-axis is the next 48 slots from `forecast_origin`. Toggle to overlay the stack-modelled fundamental price. Toggle to colour the fan by `regime_states.most_likely_regime`.

**Section C — Stack inspector.** For any selected slot: a step-chart of the supply curve from `stack_curves.curve_jsonb`, demand line overlaid, marginal unit highlighted. Hover a step → tooltip with generator name, fuel type, SRMC.

### 6.4 `/workbench` — Asset list & valuation

Two-column layout. Left: list of the user's assets (`assets` table, RLS-scoped). Click "+ New asset" or any row.

**Asset detail view.** Form for:

- Name, asset type, area
- Power (MW), Energy (MWh), Round-trip efficiency, Cycle limit
- Min/max SoC, Degradation cost (¥/MWh)

Below the form, a "Run valuation" button. On click:

1. POST to `/api/value-asset` with the asset spec.
2. Server action inserts a `valuations` row with `status='queued'`, returns the `valuation_id`.
3. Server action calls `MODAL_LSM_ENDPOINT` async with `{valuation_id, asset_id, forecast_run_id}`.
4. Frontend subscribes via Supabase Realtime to that `valuations` row.
5. As status transitions through `running` → `done`, the page renders results progressively.

**Results panel.** Total value (¥), intrinsic/extrinsic split (donut), 5/95 CI band, expected SoC envelope (line chart over the horizon), decision heatmap (slot × regime, cell colour = action). All rendered with Recharts.

### 6.5 `/lab` — Strategy lab / backtests

Pick an asset, pick a window (date range), pick one or more strategies (LSM / intrinsic / rolling-intrinsic / naive-spread). Click "Run backtest". Same async pattern as valuations: insert `backtests` row, kick off Modal, subscribe via Realtime, render P&L curves + Sharpe + max drawdown comparison when done.

### 6.6 `/analyst` — AI Analyst tab

Two-pane layout. Left: chat interface (chat history list, message thread, input box at bottom). Right: scratchpad pane that renders `agent_artifacts` (charts, tables) as the agent creates them.

User sends a message → POST to `/api/agent` → server action streams the response from the Modal agent service → tool calls and their results are inserted into `chat_messages`, charts into `agent_artifacts`, frontend renders both via Realtime subscriptions.

Each artifact has a "Pin" toggle (sets `agent_artifacts.pinned=true`, exempts from 7-day expiry).

---

## 7. Ingestion pipeline

All ingest jobs live in `apps/worker/ingest/`. Each is a Modal scheduled function. Workers write to Supabase using the service-role key.

### 7.1 Sources and schedules (JST)

| Job | Source | Schedule | Tables |
|---|---|---|---|
| `ingest_jepx_prices` | japanesepower.org CSV (v1) → direct JEPX scrape (v2) | Daily 06:00 | `jepx_spot_prices` |
| `ingest_demand` | japanesepower.org → OCCTO direct (v2) | Daily 06:00 | `demand_actuals` |
| `ingest_generation_mix` | Per-utility area-supply CSVs (TSO publications, see §7.1.1) | Daily 06:05 | `generation_mix_actuals` |
| `ingest_weather` | Open-Meteo API | Daily 06:10 | `weather_obs` |
| `ingest_fuel_prices` | CME delayed feeds | Daily 06:15 | `fuel_prices` |
| `ingest_fx` | frankfurter (ECB) | Daily 06:20 | `fx_rates` |
| `ingest_holidays` | `holidays-jp` Python package | Annual | `jp_holidays` |
| `ingest_jepx_intraday` | japanesepower.org | Daily 14:00 | `jepx_spot_prices` (auction_type='intraday') |

#### 7.1.1 Per-utility area-supply CSVs (`ingest_generation_mix`)

> **Updated 2026-05-04.** Originally the spec called for "japanesepower.org HH Data" — recon during M3 found that japanesepower.org publishes spot/intraday/demand/weather only, no fuel-mix CSV. Replaced with the official per-utility "エリア需給実績" (area supply-demand record) publications, which are the same datasets OCCTO consumes for cross-area aggregation. URL patterns are stable per-fiscal-year (`area-YYYY.csv` style) and the file shape is consistent: 3-row header (unit + multi-row column header) followed by hourly rows in `万kWh` (1 万kWh per hour = 10 MW continuous).

| Area | Operator | URL pattern | Encoding | M3 status |
|---|---|---|---|---|
| TK | TEPCO PG | `https://www.tepco.co.jp/forecast/html/images/area-{fy}.csv` | utf-8-sig | **Implemented** |
| HK | Hokkaido EPCO | `http://denkiyoho.hepco.co.jp/area/data/jukyu_{fy}_hokkaido.csv` | cp932 | v2 |
| TH | Tohoku EPCO | `https://setsuden.nw.tohoku-epco.co.jp/common/demand/juyo_{fy}_tohoku.csv` | cp932 | v2 |
| CB | Chubu EPCO | `https://powergrid.chuden.co.jp/denkiyoho/csv/area_jukyu_{fy}.csv` | cp932 | v2 |
| HR | Hokuriku EPCO | `https://www.rikuden.co.jp/nw_jyukyudata/attach/area_jukyu_{fy}.csv` | cp932 | v2 |
| KS | Kansai EPCO | `https://www.kansai-td.co.jp/yamasou/area_jukyu_{fy}.csv` | cp932 | v2 |
| CG | Chugoku EPCO | `https://www.energia.co.jp/nw/jukyuu/sys/area_jukyu_{fy}.csv` | cp932 | v2 |
| SK | Shikoku EPCO | `https://www.yonden.co.jp/nw/area_jukyu/csv/jukyu_{fy}.csv` | cp932 | v2 |
| KY | Kyushu EPCO | `https://www.kyuden.co.jp/td_area_jukyu/csv/jukyu_{fy}.csv` | cp932 | v2 |

Fiscal year `fy` is the Japanese FY (April–March), e.g. fiscal 2023 covers 2023-04-01 → 2024-03-31.

The non-TEPCO URL patterns are documented from public landing pages but not yet exercised — confirm exact paths before flipping `_AREA_SOURCES["..."].implemented = True` in `apps/worker/ingest/generation_mix.py`. The parser is generic; column-header idiosyncrasies between utilities (e.g. column name for "Tokyo area demand" varies) may require per-source adjustments.

**Fuel-bucket consolidation.** The CSV groups all fossil thermal (LNG, coal, oil, biomass-mix) into a single `火力` column. We map this to `fuel_types.code='lng_ccgt'` as the best single-bucket proxy. A v3 ingest can split via separate utility data when METI ENECHO publishes per-fuel breakouts; the schema already supports it because `generation_mix_actuals.fuel_type_id` is a free-form FK.

### 7.2 Required behaviour for every ingest job

1. **Idempotent UPSERT.** Use `ON CONFLICT DO UPDATE` so a re-run never doubles up.
2. **Schema validation.** Every row validated with Pydantic before write. Failures logged, do not abort the whole batch.
3. **Polite retry.** Exponential backoff on transient errors (5 retries, 2× factor, jitter).
4. **Audit.** Every run inserts into `compute_runs` with `kind='ingest_<source>'`, status, duration, row counts, errors.
5. **Locking.** Each job acquires a Postgres advisory lock on its name to prevent overlapping runs.

### 7.3 Stack model run (after ingest)

After the price + demand + fuel + weather ingest jobs complete, `stack/build_curve.py` runs:

1. For each area × slot in the new ingest window:
   - Pull all `generators` for the area, joined to `generator_availability` for the slot.
   - For each generator, compute SRMC: `(fuel_price_jpy_mwh / efficiency) + variable_om_jpy_mwh + carbon_cost`. Renewables and nuclear get SRMC ≈ 0. Solar/wind capacity is reduced to the area's actual solar/wind output for that slot (from `generation_mix_actuals`).
   - Sort ascending by SRMC.
   - Persist as `stack_curves.curve_jsonb` (cumulative MW and SRMC at each step).
2. Cross with demand: the marginal unit is the one whose cumulative MW first meets `demand_mw`. Persist `stack_clearing_prices`.
3. Hash the inputs (fuel prices + availability + demand) into `stack_curves.inputs_hash` for cache busting.

### 7.4 Regime state inference (after stack model)

`regime/infer_state.py` runs after the stack model, weekly:

1. Load latest 5 years of `jepx_spot_prices` per area.
2. Calibrate a 3-regime MRS (Janczura-Weron specification: base + spike + drop, independent spike distribution) per area using `statsmodels.tsa.regime_switching.MarkovRegression`. Saves model parameters as a row in `models` with `type='mrs'`.
3. Run Hamilton's filter forward, write posterior regime probabilities to `regime_states` for every historical and current slot.

### 7.5 VLSTM training (weekly, GPU)

`vlstm/train.py` — Modal scheduled function, GPU `L4`, schedule `"0 17 * * 0"` (Sunday 02:00 JST = 17:00 UTC Saturday):

1. Pull last 4 years of features from Supabase as parquet to `/tmp` on the Modal container.
2. Build the input tensor with the five blocks specified in the original brief (autoregressive, calendar, fundamentals incl. stack model output, exogenous drivers, regime probabilities).
3. Train PyTorch Lightning module with MC Dropout enabled (one mask per path, NOT per timestep — this is critical for path correlation).
4. Evaluate on held-out most-recent month: RMSE, MAPE, CRPS per area and per horizon.
5. If new model beats current production by ≥3% RMSE on at least 6 of 9 areas: insert new `models` row with `status='ready'`, mark previous one `status='deprecated'`. Otherwise insert with `status='deprecated'` and log the comparison to `compute_runs`.
6. Upload weights to Supabase Storage at `models/<model_id>/weights.pt`.

### 7.6 Forecast inference (twice daily, CPU)

`vlstm/forecast.py` — Modal scheduled function, CPU only, schedule `"0 22 * * *"` (07:00 JST) and `"0 13 * * *"` (22:00 JST):

1. Load latest production `models` (`type='vlstm'`, `status='ready'`).
2. For each of 9 areas, generate 1000 paths × 48 slots ahead.
3. Insert one `forecast_runs` row, then bulk-insert `forecast_paths` rows.
4. Auto-trigger re-valuation of all `assets` flagged `metadata->>'auto_revalue' = 'true'`.

### 7.7 LSM valuation (on-demand, CPU)

`lsm/engine.py` — Modal HTTP endpoint, CPU. Numba-accelerated. See §8 for the algorithm spec.

### 7.8 Backtest (on-demand, CPU)

`backtest/runner.py` — replays historical prices, applies the chosen strategy slot-by-slot using realised `jepx_spot_prices` as the truth, applies a slippage model, computes P&L and risk metrics.

---

## 8. LSM engine — full specification

This is the algorithmic core. It must be implemented exactly as specified and validated against Boogert & de Jong (2006) before being trusted.

### 8.1 Algorithm

Direct adaptation of Boogert & de Jong (2006). For a storage asset with state-of-charge v(t) and price S(t), step backward from terminal date T+1, regressing continuation value on basis functions of price:

```
For each path b in 1..M, simulate prices S^b(1..T+1) [supplied externally as forecast_paths]
For each volume grid point n in 1..N: initialise Y^b(T+1, n) = 0 (no terminal penalty in v1)

For t = T down to 1:
    For each volume grid point n in 1..N:
        # Regress continuation value on basis functions of price, separately per volume grid
        Fit OLS: Y^b(t+1, n) ≈ Σ_q β_q · φ_q(S^b(t))
        Save β_t,n
    
    For each path b:
        Determine action ∆v* maximising:
            h(S^b(t), ∆v) + e^(-δ) · Cˆ(t, S^b(t), v(t) + ∆v)
        subject to:
            v(t) + ∆v in [v_min, v_max]
            ∆v in [-power_mw·dt, +power_mw·dt]   (charge/discharge rate limit)
            cumulative throughput so far ≤ max_cycles_per_year * energy_mwh
        
        Apply action: v(t+1) = v(t) + ∆v, accumulate cash flow
        Update Y^b(t, ·) accordingly using interpolation between adjacent volume grid points
        (per equations 26-28 of Boogert & de Jong)

Total value = mean over paths of accumulated discounted cash flows
Intrinsic value = same algorithm using mean of paths instead of paths themselves
Extrinsic value = total - intrinsic
CI = 5th and 95th percentiles of per-path total values
```

### 8.2 BESS-specific adaptations vs the gas-storage paper

| Boogert & de Jong | BESS adaptation |
|---|---|
| `i_max(t,v)` (injection rate) | `+power_mw · dt` (clip to remaining capacity) |
| `i_min(t,v)` (withdrawal rate) | `-power_mw · dt` (clip to current SoC) |
| `c(S(t)) = (1+a1)S(t) + b1` (cost of injection) | `S(t) / round_trip_eff_one_way + degradation_jpy_mwh` |
| `p(S(t)) = (1-a2)S(t) - b2` (profit of withdrawal) | `S(t) · round_trip_eff_one_way - degradation_jpy_mwh` |
| No cycle limit | Track cumulative throughput; reject actions that would exceed `max_cycles_per_year · energy_mwh` |
| `q(v(T+1))` terminal penalty | None for v1 (BESS has no required end-state) |

Where `round_trip_eff_one_way = sqrt(round_trip_eff)`, splitting the loss symmetrically between charge and discharge.

### 8.3 Basis functions

Default: `φ(S, p_spike) = {1, S, S², S³, p_spike, p_spike·S}` where `p_spike` is the regime-spike probability from `regime_states` for that slot. This is the regime-aware extension flagged in the original brief.

Configurable via `valuations.basis_functions` JSONB. Other supported families:

- `power` — `{1, S, S², S³}` (vanilla Boogert & de Jong)
- `bspline` — cubic B-splines with K interior knots
- `power_regime` — default, as above

Validated against the paper: with `power` family on a synthetic gas-asset with the paper's parameters, the engine must reproduce 5,397,023–5,502,115 EUR (the range from Table 2) ±1%.

### 8.4 Performance targets

- `(M=1000 paths, N=101 volume grid, T=17,520 slots)` valuation: **≤ 60 seconds on Modal CPU `cpu=4.0`**.
- Numba JIT must be applied to the inner loop with `parallel=True`. Without it, a Python loop hits 30+ minutes; this is non-negotiable.
- The volume-action grid uses interpolation between adjacent volume points (per §4.2 of Boogert & de Jong) to keep N small.

### 8.5 Validation gate — `lsm/tests/test_boogert_dejong_replication.py`

This test must pass before the LSM engine can be used on any real asset.

```python
def test_replicates_boogert_dejong_high_volatility():
    """
    Replicate Table 2, P3 case, 5000 paths: target value 5,502,115 EUR ± 1%.
    Setup matches the paper's standard contract (§3.2):
      - v_min = 0, v_max = 250,000 MWh
      - v_start = v_end = 100,000 MWh
      - i_max = 2,500 MWh/day, i_min = -7,500 MWh/day
      - high volatility case: σ = 9.45%, κ = 0.05, daily resolution, 365 days
      - one-factor Schwartz mean-reverting price process
      - basis: power family up to S^3
      - no transaction costs, no penalty
    """
    paths = simulate_schwartz_1997_paths(
        n_paths=5000, sigma=0.0945, kappa=0.05, T_days=365, S0=15.0
    )
    value, ci_lo, ci_hi = run_lsm(
        paths=paths,
        asset=GAS_ASSET_FROM_PAPER,
        basis="power",
    )
    assert 5_447_010 <= value <= 5_557_136  # ±1% of 5,502,115
```

If this test fails, the engine is not trusted on real BESS configurations. This test is the convergence diagnostic gate from the paper's §4.1.

---

## 9. AI agent specification

### 9.1 Architecture

The agent backend runs as a FastAPI service on Modal at `MODAL_AGENT_ENDPOINT`. The Vercel `/api/agent` route is a thin relay — it forwards user messages, attaches the user's JWT, and streams the response back to the client.

```
USER → Vercel /api/agent → (JWT-attached HTTPS) → Modal FastAPI agent service
                                                          │
                                                          ├→ OpenAI API (function-calling loop)
                                                          ├→ Postgres (via SUPABASE_AGENT_READONLY_DB_URL — SELECT only, role-enforced)
                                                          └→ Postgres (via service role: insert chat_messages, agent_artifacts)
```

The agent service uses **two separate Postgres connections**:

1. **`SUPABASE_AGENT_READONLY_DB_URL`** (role: `agent_readonly`) — for executing user-facing queries via the `query_data` tool. Physically cannot mutate state.
2. **Service role** — for inserting `chat_messages`, `agent_artifacts`, and `compute_runs` for audit. Never exposed to the LLM.

This is the layered defence we landed on — RLS scopes data by user, the `agent_readonly` role enforces read-only at the database level, and the agent backend code only ever issues `SELECT` through that connection. Three layers, no DuckDB.

### 9.2 Tools

All tools defined in `apps/worker/agent/tools.py`. Schema for OpenAI function-calling must match exactly.

| Tool | Parameters | Returns | Implementation notes |
|---|---|---|---|
| `query_data` | `sql: string` (must start with `SELECT` or `WITH`) | result rows (≤ 10,000) | Executes via `agent_readonly` connection. 30s timeout. Parses with `sqlglot`, rejects non-SELECT statements before sending to DB. RLS still applies for user-scoped tables. |
| `describe_schema` | `table_name?: string` | columns, types, sample 3 rows | Reads `data_dictionary` for descriptions and units. |
| `create_chart` | `type: 'line'\|'bar'\|'scatter'\|'heatmap'\|'area'`, `data_query: string`, `encoding: object`, `title: string` | `agent_artifact_id` | Runs `data_query` (read-only), composes a Plotly JSON figure spec, inserts into `agent_artifacts`. |
| `run_correlation` | `cols: string[]`, `filter_sql?: string`, `method: 'pearson'\|'spearman'` | correlation matrix + p-values | pandas `.corr()` plus significance tests. |
| `fit_quick_model` | `target: string`, `features: string[]`, `model_type: 'linear'\|'ridge'\|'random_forest'`, `train_window_days: int` | held-out RMSE, R², feature importances | scikit-learn fit on a time-bounded slice. **Never persists** to `models`. |
| `value_what_if` | `asset_id: uuid`, `overrides: { round_trip_eff?, power_mw?, energy_mwh?, max_cycles_per_year? }` | summary of the resulting valuation | Calls the LSM endpoint with overrides applied to a copy of the asset spec. **Does not mutate** the underlying `assets` row. Result stored in `compute_runs` only. |
| `get_user_assets` | none | list of user's assets | RLS-scoped to the calling user. |

### 9.3 System prompt

`apps/worker/agent/prompts.py` — a single template populated at request time. Must include:

1. Domain context (JEPX, BESS, the three engines, the regime model).
2. The full schema overview from `data_dictionary` (auto-generated from table contents).
3. **Unit handling rules.** Especially: ¥/kWh ≠ ¥/MWh (factor of 1000). The agent must always report units. Confusing these has cost real desks real money.
4. Available tools and when to use each.
5. Examples of good interactions (include 3-5).
6. Safety: never speculate when a tool can answer, never claim financial-advice authority.

### 9.4 Safety rails (enforced server-side)

- **Read-only DB** — enforced at three layers (sqlglot parse, `agent_readonly` Postgres role, RLS).
- **Token budget** — per session: 128,000 tokens of total OpenAI context (matches GPT-4o/4-turbo). Hard cut once exceeded.
- **Audit** — every tool call logged to `compute_runs` with `kind='agent_tool_call'`, including inputs and outputs. Inspectable in a per-session UI.
- **No model promotion** — `fit_quick_model` and `value_what_if` never write to `models`, `valuations`, or `assets`. Their results live only in `compute_runs` and `agent_artifacts`.
- **Artifact expiry** — `agent_artifacts` rows older than 7 days are deleted nightly unless `pinned=true`.

### 9.5 Error handling

- LLM call fails → insert assistant message with content "I hit an error reaching the model. Try again?" and log to `compute_runs`.
- Tool returns malformed result → return a structured error to the LLM so it can retry with different parameters (one retry max).
- `query_data` timeout → return "Query took too long; try narrowing the time range or aggregating."
- SQL parse rejection → return the parse error to the LLM so it can rewrite.

---

## 10. Realtime wiring

Three frontend hooks, all in `apps/web/src/hooks/`:

```ts
// useValuationStream(valuationId): { valuation, decisions, status }
// Subscribes to UPDATE on valuations row. Once status='done', also fetches valuation_decisions.

// useChatMessages(sessionId): { messages, artifacts, sendMessage, pending }
// Subscribes to INSERT/UPDATE on chat_messages and agent_artifacts filtered by session_id.

// useRealtimeForecast(areaId): { latestRun, paths }
// Subscribes to INSERT on forecast_runs filtered by area_id; on new run, fetches paths.
```

---

## 11. Compute orchestration (Modal)

Modal app entry: `apps/worker/modal_app.py`. Single app, multiple functions.

```python
import modal

app = modal.App("jepx-storage")

# Shared image with all dependencies
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("requirements.txt")
)

# Secrets — set in Modal dashboard, not committed
secrets = [
    modal.Secret.from_name("jepx-supabase"),
    modal.Secret.from_name("jepx-openai"),
]

# Scheduled: weekly VLSTM retrain (GPU)
@app.function(image=image, gpu="L4", timeout=3600,
              schedule=modal.Cron("0 17 * * 0"), secrets=secrets)
def train_vlstm_weekly(): ...

# Scheduled: daily forecast inference (CPU)
@app.function(image=image, cpu=4.0, timeout=600,
              schedule=modal.Cron("0 22,13 * * *"), secrets=secrets)
def generate_forecasts_daily(): ...

# Scheduled: daily ingest jobs
@app.function(image=image, cpu=2.0, schedule=modal.Cron("0 21 * * *"), secrets=secrets)
def ingest_daily(): ...   # fans out to all ingest sub-jobs

# Scheduled: nightly artifact GC
@app.function(image=image, schedule=modal.Cron("0 18 * * *"), secrets=secrets)
def cleanup_artifacts(): ...

# HTTP endpoint: on-demand LSM valuation
@app.function(image=image, cpu=4.0, timeout=300, secrets=secrets)
@modal.web_endpoint(method="POST", label="lsm-value")
def lsm_value(req): ...

# HTTP endpoint: AI agent service (FastAPI app)
@app.function(image=image, cpu=2.0, timeout=120, secrets=secrets,
              allow_concurrent_inputs=10)
@modal.asgi_app(label="agent")
def agent_app():
    from agent.service import build_app
    return build_app()
```

Tokyo region is configured at the workspace level in Modal's dashboard, not per-function.

---

## 12. Milestone checkpoints (execute sequentially, STOP at each)

At each STOP: commit with a clean message, tell the operator what to test, wait for confirmation before continuing.

### Milestone 1 — Scaffold (2-3 days)

- Turborepo monorepo with `apps/web`, `apps/worker`, `packages/shared-types`.
- Next.js 14 + Tailwind + shadcn/ui installed in `apps/web`. Landing page + login route + `/dashboard` placeholder.
- `apps/worker` Python project with `pyproject.toml`, Modal CLI authenticated, `modal_app.py` deploys an empty stub.
- `CLAUDE.md` at repo root + one in each subdirectory.
- Operator: `npm run dev` shows landing page; `modal deploy apps/worker/modal_app.py` succeeds. **STOP.**

### Milestone 2 — Database (1-2 days)

- All three migration files written and tested against a local Supabase instance.
- Reference data seed script (`apps/worker/seed/load_reference.py`) loads 9 areas, ~12 fuel types, ~8 unit types, holidays.
- Data dictionary YAML + loader script.
- Operator: pastes migrations in Supabase SQL editor, runs seed scripts, verifies tables and `agent_readonly` role exist. **STOP.**

### Milestone 3 — Tier 1 ingest (3-5 days)

- Six ingest jobs (`jepx_prices`, `demand`, `generation_mix`, `weather`, `fx`, `holidays`) running on Modal's daily schedule, sourced from japanesepower.org + Open-Meteo + frankfurter.
- 5 years of historical data backfilled.
- Sentry wired up, errors logged to `compute_runs`.
- Admin status page at `/dashboard` showing per-source ingest health.
- Operator: opens dashboard, sees the latest 48 slots of every area refreshing daily; confirms the backfill range covers 2020–2025. **STOP — this is the first place real data quality matters.**

### Milestone 4 — Stack model (3-4 days)

- Generator master populated for the top 100 thermal units across the 9 areas (manual curation, ~2 weeks of analyst time but checked in as a YAML seed).
- `stack/build_curve.py` running daily, populating `stack_curves` and `stack_clearing_prices`.
- Backtest comparing stack-modelled clearing price to realised JEPX price: aim for RMSE < ¥3/kWh on routine slots.
- Frontend `/dashboard` Section C (stack inspector) renders for the selected slot.
- Operator: picks 5 slots across different areas/seasons, confirms the modelled clearing price is within reasonable range of realised. **STOP.**

### Milestone 5 — Regime calibration (2-3 days)

- `regime/mrs_calibrate.py` fits 3-regime MRS per area, persists to `models` and `regime_states`.
- Validation: for the 2021 Jan/Feb spike window, P(spike) ≥ 0.7 on at least 80% of those slots in Tokyo and Tohoku.
- Operator: queries `regime_states` for Jan-Feb 2021 in Tokyo, confirms spike regime dominates. **STOP.**

### Milestone 6 — VLSTM (1-2 weeks — biggest single milestone)

- `vlstm/data.py` builds the 5-block feature tensor, exports parquet to Supabase Storage.
- `vlstm/model.py` PyTorch Lightning module with MC Dropout, one-mask-per-path sampling.
- `vlstm/train.py` runs end-to-end on Modal GPU, registers a model in `models`.
- `vlstm/forecast.py` generates 1000 paths × 48 slots × 9 areas in <60s on CPU, writes to `forecast_paths`.
- Validation: per-horizon RMSE comparison vs a naive ARIMA baseline. VLSTM must beat ARIMA on at least 6 of 9 areas at 24h horizon.
- Frontend Section B (forecast fan chart) renders.
- Operator: opens dashboard, picks any area, confirms a fan chart with non-zero CI band appears. **STOP — second highest-risk milestone.**

### Milestone 7 — LSM engine (1-2 weeks)

- `lsm/engine.py` Numba implementation, deployed as a Modal HTTP endpoint.
- `test_boogert_dejong_replication.py` passes — this is the gate, do not proceed if it fails.
- Frontend `/workbench` asset config form + valuation flow.
- Async pattern: queue a `valuations` row, kick Modal, frontend subscribes via Realtime.
- Results page renders intrinsic/extrinsic split, SoC envelope, decision heatmap.
- Operator: configures a 100MW/400MWh BESS in Tokyo, runs valuation, gets a result in <60s. **STOP.**

### Milestone 8 — Backtest engine (1 week)

- `backtest/runner.py` replays the four strategies (LSM, intrinsic, rolling-intrinsic, naive-spread) on realised history.
- Slippage model in `backtest/slippage.py`.
- `/lab` strategy comparison page.
- Operator: picks a 12-month window, runs all four strategies on a configured asset, gets P&L curves. **STOP.**

### Milestone 9 — AI agent (1-2 weeks)

- `agent/service.py` FastAPI app deployed as Modal ASGI endpoint.
- All seven tools implemented with strict input validation.
- `query_data` parsed by sqlglot, rejected unless SELECT/WITH; runs through `agent_readonly` Postgres connection.
- System prompt populated from `data_dictionary`.
- Token budget enforcement, audit logging.
- Frontend `/analyst` chat + scratchpad UI.
- Operator: runs the §13 smoke-test script, confirms each scenario passes. **STOP.**

### Milestone 10 — Polish (1 week)

- Loading skeletons, empty states, error boundaries.
- Mobile-responsive read-only views (full editing experience can stay desktop-only for v1).
- Sentry source maps + PostHog events on every primary action.
- Performance: Lighthouse score ≥ 90 on `/dashboard`; LSM P95 latency ≤ 60s; agent first-token P95 ≤ 2s.
- Operator: full walkthrough of all four tabs, confirms no rough edges. **STOP — ready to demo.**

---

## 13. Agent smoke-test script (Milestone 9 verification)

The agent passes Milestone 9 when all seven scenarios below produce sensible output without errors.

1. *"What was the average Tokyo peak price (17:00–20:00) in August 2024?"* — should call `query_data`, return a single number with units.
2. *"Compare Tokyo and Kansai peak-offpeak spreads in winter vs summer since 2022, and chart it."* — should call `query_data` then `create_chart`. Chart appears in scratchpad.
3. *"How does Tokyo morning peak price correlate with previous-day cloud cover?"* — should call `run_correlation`, return a sensible coefficient.
4. *"What if my BESS had 92% round-trip efficiency instead of 88%?"* (in context of an existing asset) — should call `value_what_if`, return a comparison summary. The underlying `assets` row is unchanged.
5. *"Show me my assets."* — should call `get_user_assets`. Only the calling user's assets appear (RLS verified by signing in as a second user and confirming isolation).
6. *"Why does our model predict a spike on Friday morning?"* — should call `query_data` against `regime_states` and return a reasoned explanation citing P(spike).
7. **Adversarial:** *"Run UPDATE jepx_spot_prices SET price_jpy_kwh = 0;"* — must be rejected at the sqlglot layer with a clear error. If somehow it bypasses, the `agent_readonly` Postgres role fails the statement. Verify both layers independently.

---

## 14. Not in scope (do not build for v1)

- Multi-market co-optimisation (day-ahead + intraday + ancillary services). The asset spec supports it but the LSM engine optimises against day-ahead spot only.
- Two-factor Schwartz–Smith price model — listed as v2 in the original brief.
- Direct JEPX scraping. v1 ingests via japanesepower.org. Direct scrape is a Phase 3+ migration task.
- TSO outage feeds — v1 uses static availability assumptions.
- Capacity market and LDES auction result ingest.
- Paid feeds (ICE Connect, EEX, Argus, Platts).
- PPA structuring tools.
- Public API for programmatic access.
- Workspace / team features (shared portfolios, comments).
- Mobile-first editing experience (mobile is read-only for v1).
- Notifications, push, PWA features.
- Subagents in the AI Analyst tab — v1 is a single agent with a fixed toolset.
- Full variational LSTM (Bayes-by-Backprop). v1 uses MC Dropout, which is the literature consensus for practical probabilistic price forecasting.
- DS-HDP-HMM regime detection. v1 uses 3-regime Janczura-Weron MRS.
- DuckDB anywhere in the stack.
- TimescaleDB.
- Prefect / Airflow.
- Redis.
- LangChain / LangGraph.

---

## 15. Working agreement with the build agent

- **This spec is the source of truth.** If something is genuinely ambiguous, ask. Don't guess on schema, units, or algorithm details — those are non-negotiable. Minor naming and structure choices, decide and move on.
- **Stop at every milestone checkpoint** and let the operator test. Never blast through to the end.
- **Surface errors clearly.** Don't silently work around. Show the error, propose a fix.
- **Commit after each milestone** with a descriptive message that names the milestone.
- **Use idiomatic Next.js 14 App Router patterns** — Server Components by default, Client Components with explicit `'use client'`, Route Handlers for APIs, server actions for mutations.
- **Validate every external boundary.** Pydantic in Python, zod in TypeScript. No untyped data crosses a process boundary.
- **Wrap every external call** (LLM, OpenAI, Modal HTTP, Open-Meteo, japanesepower.org, frankfurter, CME) in try/except with audit logging to `compute_runs`.
- **Numba is mandatory for the LSM inner loop.** Without `@numba.jit(parallel=True)` the engine is unusably slow. The replication test exists to catch any regression on this.
- **The Boogert & de Jong replication test is the gate for the LSM engine.** If it fails, do not proceed to Milestone 8.
- **Write tests as you go**, not at the end. At minimum: every ingest job has a test against a saved fixture, every algorithmic module (stack, MRS, VLSTM data prep, LSM) has at least one regression test.
- **Tokyo region everywhere.** Supabase `ap-northeast-1`, Vercel `hnd1`, Modal Tokyo workspace. Latency matters when you're chaining 5 calls per page render.

---

## 16. Start here

1. Confirm you have read and understood this entire spec.
2. Ask at most 3 genuinely blocking questions. Don't invent questions — most things are answered above.
3. Begin Milestone 1: scaffold. Execute it. Stop and tell the operator exactly how to verify before proceeding.

Go.
