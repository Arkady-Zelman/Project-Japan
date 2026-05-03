-- ============================================================
-- JEPX-Storage — Row-Level Security policies + Realtime publication
-- Source of truth: BUILD_SPEC.md §5.2 (lines 614–700) + §5.3 step 2 (line 730).
-- ============================================================

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
-- Note: the AI agent gets a parallel set of "agent_read_*" policies in
-- 003_agent_readonly_role.sql — added there because the role doesn't exist yet here.
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

-- ============================================================
-- REALTIME PUBLICATION
-- Frontend subscribes to these channels for live status updates
-- (e.g. valuations row → done; new chat_messages append).
-- ============================================================

alter publication supabase_realtime add table
  valuations,
  backtests,
  forecast_runs,
  chat_messages,
  agent_artifacts,
  compute_runs;
