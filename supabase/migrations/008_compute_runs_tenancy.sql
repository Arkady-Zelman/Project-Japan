-- ============================================================
-- Protect user-triggered compute_runs audit rows.
--
-- Earlier workers wrote lsm_valuation, backtest, and agent_tool_call rows with
-- user_id NULL. The original RLS policy treated every NULL-user row as public
-- so anonymous visitors could read user valuation/backtest/agent audit output.
-- Backfill owners where possible, then only expose NULL-user rows for
-- system/demo job kinds that are intentionally public health telemetry.
-- ============================================================

update compute_runs cr
   set user_id = v.user_id
  from valuations v
 where cr.kind = 'lsm_valuation'
   and cr.user_id is null
   and cr.input->>'valuation_id' = v.id::text
   and v.user_id is not null;

update compute_runs cr
   set user_id = b.user_id
  from backtests b
 where cr.kind = 'backtest'
   and cr.user_id is null
   and cr.input->>'backtest_id' = b.id::text
   and b.user_id is not null;

update compute_runs
   set user_id = (input->>'user_id')::uuid
 where kind = 'agent_tool_call'
   and user_id is null
   and input ? 'user_id'
   and input->>'user_id' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

drop policy if exists "users_own_compute_runs" on compute_runs;

create policy "users_own_compute_runs" on compute_runs for select
  using (
    user_id = auth.uid()
    or (
      user_id is null
      and kind in (
        'ingest_jepx_prices',
        'ingest_jepx_intraday',
        'ingest_demand',
        'ingest_generation_mix',
        'ingest_generator_availability',
        'ingest_weather',
        'ingest_fuel_prices',
        'ingest_fx',
        'ingest_holidays',
        'stack_build',
        'stack_backtest',
        'stack_load_generators',
        'synthesize_demand',
        'regime_calibrate',
        'regime_infer',
        'regime_validate',
        'vlstm_train',
        'vlstm_validate',
        'forecast_inference',
        'demo_asset'
      )
    )
  );
