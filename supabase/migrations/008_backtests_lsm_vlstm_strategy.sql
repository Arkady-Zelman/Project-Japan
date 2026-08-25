-- ============================================================
-- 008_backtests_lsm_vlstm_strategy.sql
-- ============================================================
-- The Lab form and /api/run-backtest already accept `lsm_vlstm`, but
-- backtests.strategy's check constraint still lists only the M8 quartet.
-- Inserting a VLSTM-driven row (or a mixed batch that includes it) fails
-- the whole statement, so a user ticking "LSM (VLSTM-driven)" cannot run
-- any of the selected strategies.
-- ============================================================

alter table backtests drop constraint if exists backtests_strategy_check;

alter table backtests add constraint backtests_strategy_check
  check (strategy in (
    'lsm',
    'intrinsic',
    'rolling_intrinsic',
    'naive_spread',
    'lsm_vlstm'
  ));
