-- ============================================================
-- JEPX-Storage — agent_readonly role
-- Source of truth: BUILD_SPEC.md §5.3 (lines 705–724).
--
-- The AI agent connects to Postgres using this role. It physically cannot mutate data.
-- This is a defence-in-depth on top of "the agent backend only calls SELECT" — even if a
-- prompt-injection slips through, the database refuses writes.
-- ============================================================

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

-- ============================================================
-- RLS read policies for `agent_readonly`
-- The "auth_read_*" policies in 002_rls.sql only target the `authenticated` role,
-- so an agent_user session sees zero rows by default. Mirror those policies for
-- agent_readonly on the public market/reference/model tables. The user-scoped
-- tables (assets, portfolios, valuations, etc.) intentionally get no agent
-- policy — combined with the GRANT-level revokes above, the agent is blind to
-- private user data even on SELECT.
-- ============================================================

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
