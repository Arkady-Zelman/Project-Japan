-- ============================================================
-- 008_backtests_lsm_vlstm_strategy.sql
-- ============================================================
-- M10 exposed the VLSTM-driven LSM strategy in the Lab UI/API and worker
-- registry, but the original backtests.strategy CHECK constraint still
-- rejected it. Keep the DB contract aligned with the shipped strategy set.
-- ============================================================

alter table backtests
  drop constraint if exists backtests_strategy_check;

alter table backtests
  add constraint backtests_strategy_check
  check (strategy in ('lsm', 'intrinsic', 'rolling_intrinsic', 'naive_spread', 'lsm_vlstm'));
