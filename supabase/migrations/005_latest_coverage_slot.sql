-- Stored function that returns the latest demand_actuals.slot_start where
-- every JEPX utility (≥9 distinct areas) has a non-null demand_mw, looking
-- back up to `lookback_days` (default 14). Used by /api/regional-balance so
-- the dashboard's first paint shows a fully-covered snapshot instead of a
-- half-empty one when HK/TH publish 1-2 days late.

create or replace function latest_full_coverage_slot(
  lookback_days int default 14,
  min_areas int default 9
) returns timestamptz
language sql stable as $$
  select slot_start
  from demand_actuals
  where slot_start >= now() - (lookback_days || ' days')::interval
  group by slot_start
  having count(*) filter (where demand_mw is not null) >= min_areas
  order by slot_start desc
  limit 1;
$$;

-- Allow service-role and authenticated callers to invoke it. anon role too,
-- since /api/regional-balance is anonymous-readable per BUILD_SPEC §6.
grant execute on function latest_full_coverage_slot(int, int) to anon, authenticated, service_role;
