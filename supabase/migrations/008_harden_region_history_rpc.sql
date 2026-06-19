-- ============================================================
-- 008_harden_region_history_rpc.sql
-- ============================================================
-- 007 exposed region_history directly to anon as a SECURITY DEFINER RPC.
-- Keep the public dashboard route working via the server client, but bound
-- direct RPC calls at the database layer and remove anonymous execution.
-- ============================================================

create or replace function region_history(
  p_area_codes text[],
  p_metric text,
  p_days int
)
returns table (
  day date,
  area_code text,
  value double precision
)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_days int := least(greatest(coalesce(p_days, 30), 1), 90);
  v_area_codes text[];
begin
  if p_metric not in ('price', 'vre_share', 'balance_pct') then
    raise exception 'invalid region_history metric: %', p_metric
      using errcode = '22023';
  end if;

  select coalesce(array_agg(distinct requested.code), array[]::text[])
  into v_area_codes
  from unnest(coalesce(p_area_codes, array[]::text[])) as requested(code)
  where requested.code in ('TK','HK','TH','CB','HR','KS','CG','SK','KY');

  if cardinality(v_area_codes) = 0 then
    return;
  end if;

  if p_metric = 'price' then
    return query
    select
      (jsp.slot_start at time zone 'UTC')::date as day,
      a.code as area_code,
      avg(jsp.price_jpy_kwh)::double precision as value
    from jepx_spot_prices jsp
    join areas a on a.id = jsp.area_id
    where a.code = any(v_area_codes)
      and jsp.auction_type = 'day_ahead'
      and jsp.slot_start >= now() - make_interval(days => v_days)
      and jsp.price_jpy_kwh is not null
    group by 1, 2
    order by 1, 2;

  elsif p_metric = 'vre_share' then
    return query
    with gen as (
      select
        (gma.slot_start at time zone 'UTC')::date as day,
        gma.area_id,
        sum(case when lower(ft.code) in ('solar','wind','hydro','vre')
                 then coalesce(gma.output_mw, 0) else 0 end)::double precision as vre_mw,
        sum(coalesce(gma.output_mw, 0))::double precision as total_mw
      from generation_mix_actuals gma
      join fuel_types ft on ft.id = gma.fuel_type_id
      where gma.slot_start >= now() - make_interval(days => v_days)
      group by 1, 2
    )
    select
      gen.day,
      a.code as area_code,
      case when gen.total_mw > 0 then gen.vre_mw / gen.total_mw else null end as value
    from gen
    join areas a on a.id = gen.area_id
    where a.code = any(v_area_codes)
    order by 1, 2;

  elsif p_metric = 'balance_pct' then
    return query
    with day_demand as (
      select
        (slot_start at time zone 'UTC')::date as day,
        area_id,
        sum(demand_mw)::double precision as demand_total
      from demand_actuals
      where slot_start >= now() - make_interval(days => v_days)
        and demand_mw is not null
      group by 1, 2
    ),
    day_gen as (
      select
        (slot_start at time zone 'UTC')::date as day,
        area_id,
        sum(coalesce(output_mw, 0))::double precision as gen_total
      from generation_mix_actuals
      where slot_start >= now() - make_interval(days => v_days)
      group by 1, 2
    )
    select
      coalesce(d.day, g.day) as day,
      a.code as area_code,
      case when coalesce(d.demand_total, 0) > 0
           then (coalesce(g.gen_total, 0) - d.demand_total) / d.demand_total
           else null end::double precision as value
    from day_demand d
    full outer join day_gen g on d.area_id = g.area_id and d.day = g.day
    join areas a on a.id = coalesce(d.area_id, g.area_id)
    where a.code = any(v_area_codes)
    order by 1, 2;
  end if;
end;
$$;

revoke all on function region_history(text[], text, int) from public;
revoke execute on function region_history(text[], text, int) from anon;
grant execute on function region_history(text[], text, int) to authenticated, service_role;
