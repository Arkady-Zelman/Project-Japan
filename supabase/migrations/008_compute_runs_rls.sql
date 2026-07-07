-- Tighten compute_runs visibility.
--
-- 002_rls.sql allowed every row with user_id IS NULL to be read by any
-- authenticated or anonymous client. That was too broad once user-triggered
-- jobs and agent tool calls also wrote audit rows: old rows without user_id
-- can contain valuation IDs, P&L summaries, SQL text, and stack traces.
--
-- Public clients may only see explicit system/cron telemetry. User-scoped
-- rows are visible to their owner only.

drop policy if exists "users_own_compute_runs" on compute_runs;
drop policy if exists "public_system_compute_runs" on compute_runs;

create policy "users_own_compute_runs" on compute_runs for select
  to authenticated
  using (user_id = auth.uid());

create policy "public_system_compute_runs" on compute_runs for select
  to anon, authenticated
  using (
    user_id is null
    and kind = any (array[
      'ingest_jepx_prices',
      'ingest_jepx_intraday',
      'ingest_demand',
      'ingest_generation_mix',
      'ingest_generator_availability',
      'ingest_weather',
      'ingest_fx',
      'ingest_fuel_prices',
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
      'forecast_path_retention',
      'demo_asset'
    ])
  );
