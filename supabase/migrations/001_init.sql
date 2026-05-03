-- ============================================================
-- JEPX-Storage — initial schema
-- Source of truth: BUILD_SPEC.md §5 (lines 230–612).
-- ============================================================

-- ============================================================
-- EXTENSIONS
-- ============================================================
create extension if not exists pgcrypto;
create extension if not exists "uuid-ossp";
create extension if not exists pg_stat_statements;

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
