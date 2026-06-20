-- ============================================================
-- 008_region_history_jst_metrics.sql
-- ============================================================
-- Correct region_history daily aggregation:
--   - bucket days in Asia/Tokyo, not UTC
--   - compute documented daily averages from slot-level metrics
--   - emit NULL, not -100%, when demand exists but generation is missing
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
begin
  if p_metric = 'price' then
    return query
    select
      (jsp.slot_start at time zone 'Asia/Tokyo')::date as day,
      a.code as area_code,
      avg(jsp.price_jpy_kwh)::double precision as value
    from jepx_spot_prices jsp
    join areas a on a.id = jsp.area_id
    where a.code = any(p_area_codes)
      and jsp.auction_type = 'day_ahead'
      and jsp.slot_start >= now() - (p_days::text || ' days')::interval
      and jsp.price_jpy_kwh is not null
    group by 1, 2
    order by 1, 2;

  elsif p_metric = 'vre_share' then
    return query
    with slot_gen as (
      select
        (gma.slot_start at time zone 'Asia/Tokyo')::date as day,
        gma.slot_start,
        gma.area_id,
        sum(case when lower(ft.code) in ('solar','wind','hydro','vre')
                 then coalesce(gma.output_mw, 0) else 0 end)::double precision as vre_mw,
        sum(coalesce(gma.output_mw, 0))::double precision as total_mw
      from generation_mix_actuals gma
      join fuel_types ft on ft.id = gma.fuel_type_id
      where gma.slot_start >= now() - (p_days::text || ' days')::interval
      group by 1, 2, 3
    ),
    gen as (
      select
        slot_gen.day,
        slot_gen.area_id,
        avg(case when total_mw > 0 then vre_mw / total_mw else null end)::double precision as value
      from slot_gen
      group by slot_gen.day, slot_gen.area_id
    )
    select
      gen.day,
      a.code as area_code,
      gen.value
    from gen
    join areas a on a.id = gen.area_id
    where a.code = any(p_area_codes)
    order by 1, 2;

  elsif p_metric = 'balance_pct' then
    return query
    with slot_demand as (
      select
        (slot_start at time zone 'Asia/Tokyo')::date as day,
        slot_start,
        area_id,
        avg(demand_mw)::double precision as demand_mw
      from demand_actuals
      where slot_start >= now() - (p_days::text || ' days')::interval
        and demand_mw is not null
      group by 1, 2, 3
    ),
    slot_gen as (
      select
        (slot_start at time zone 'Asia/Tokyo')::date as day,
        slot_start,
        area_id,
        sum(coalesce(output_mw, 0))::double precision as gen_mw
      from generation_mix_actuals
      where slot_start >= now() - (p_days::text || ' days')::interval
      group by 1, 2, 3
    ),
    slot_balance as (
      select
        d.day,
        d.area_id,
        case when d.demand_mw > 0 and g.gen_mw is not null
             then (g.gen_mw - d.demand_mw) / d.demand_mw
             else null end::double precision as balance_pct
      from slot_demand d
      left join slot_gen g on d.area_id = g.area_id and d.slot_start = g.slot_start
    ),
    day_balance as (
      select
        slot_balance.day,
        slot_balance.area_id,
        avg(balance_pct)::double precision as value
      from slot_balance
      group by slot_balance.day, slot_balance.area_id
    )
    select
      b.day,
      a.code as area_code,
      b.value
    from day_balance b
    join areas a on a.id = b.area_id
    where a.code = any(p_area_codes)
    order by 1, 2;
  end if;
  return;
end;
$$;

grant execute on function region_history(text[], text, int) to anon, authenticated;
