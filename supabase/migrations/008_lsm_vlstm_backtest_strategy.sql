-- Allow the authenticated backtest API and worker registry to queue the
-- VLSTM-driven LSM strategy that was added after the initial schema.
alter table backtests drop constraint if exists backtests_strategy_check;
alter table backtests
  add constraint backtests_strategy_check
  check (strategy in ('lsm','intrinsic','rolling_intrinsic','naive_spread','lsm_vlstm'));
