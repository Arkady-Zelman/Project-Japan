-- ============================================================
-- 008_compute_runs_rls.sql
-- ============================================================
-- `compute_runs.user_id IS NULL` used to mean "public/system", but several
-- user-triggered worker paths historically wrote NULL audit rows. Keep true
-- system health visible to the public dashboard while denying anonymous and
-- cross-user reads of valuation/backtest/agent-tool audit payloads.
-- ============================================================

drop policy if exists "users_own_compute_runs" on compute_runs;
drop policy if exists "users_read_own_compute_runs" on compute_runs;
drop policy if exists "public_read_system_compute_runs" on compute_runs;

create policy "users_read_own_compute_runs" on compute_runs for select
  to authenticated
  using (user_id = auth.uid());

create policy "public_read_system_compute_runs" on compute_runs for select
  to anon, authenticated
  using (
    user_id is null
    and kind in (
      'ingest_jepx_prices',
      'ingest_jepx_intraday',
      'ingest_demand',
      'ingest_generation_mix',
      'ingest_weather',
      'ingest_fx',
      'ingest_fuel_prices',
      'ingest_holidays',
      'ingest_generator_availability',
      'synthesize_demand',
      'stack_load_generators',
      'stack_build',
      'stack_backtest',
      'regime_calibrate',
      'regime_infer',
      'regime_validate',
      'vlstm_train',
      'vlstm_validate',
      'forecast_inference',
      'demo_asset'
    )
  );
