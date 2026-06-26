-- Allow the VLSTM-driven LSM strategy exposed by the lab UI/API.
alter table backtests
  drop constraint if exists backtests_strategy_check;

alter table backtests
  add constraint backtests_strategy_check
  check (strategy in ('lsm','intrinsic','rolling_intrinsic','naive_spread','lsm_vlstm'));
