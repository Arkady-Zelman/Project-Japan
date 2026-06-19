-- ============================================================
-- 008_harden_region_history.sql
-- ============================================================
-- `region_history` is executable by anon/authenticated users so browser
-- clients can call it through Supabase RPC. The Next.js route already
-- constrains metric/day/area inputs, but direct RPC callers bypass that route.
-- Keep the same public surface while enforcing the same bounds inside the
-- SECURITY DEFINER function.
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
  allowed_codes constant text[] := array['TK','HK','TH','CB','HR','KS','CG','SK','KY'];
begin
  if p_metric is null or p_metric not in ('vre_share', 'balance_pct', 'price') then
    raise exception 'invalid metric: %', p_metric
      using errcode = '22023';
  end if;

  if p_days is null or p_days not in (7, 30, 90) then
    raise exception 'invalid days: %', p_days
      using errcode = '22023';
  end if;

  if p_area_codes is null
     or cardinality(p_area_codes) = 0
     or cardinality(p_area_codes) > cardinality(allowed_codes)
     or exists (
       select 1
       from unnest(p_area_codes) as c(code)
       where c.code is null or not (c.code = any(allowed_codes))
     ) then
    raise exception 'invalid area codes'
      using errcode = '22023';
  end if;

  if p_metric = 'price' then
    return query
    select
      (jsp.slot_start at time zone 'UTC')::date as day,
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
    with gen as (
      select
        (gma.slot_start at time zone 'UTC')::date as day,
        gma.area_id,
        sum(case when lower(ft.code) in ('solar','wind','hydro','vre')
                 then coalesce(gma.output_mw, 0) else 0 end)::double precision as vre_mw,
        sum(coalesce(gma.output_mw, 0))::double precision as total_mw
      from generation_mix_actuals gma
      join fuel_types ft on ft.id = gma.fuel_type_id
      join areas a on a.id = gma.area_id
      where a.code = any(p_area_codes)
        and gma.slot_start >= now() - (p_days::text || ' days')::interval
      group by 1, 2
    )
    select
      gen.day,
      a.code as area_code,
      case when gen.total_mw > 0 then gen.vre_mw / gen.total_mw else null end as value
    from gen
    join areas a on a.id = gen.area_id
    order by 1, 2;

  elsif p_metric = 'balance_pct' then
    return query
    with requested_areas as (
      select id, code
      from areas
      where code = any(p_area_codes)
    ),
    day_demand as (
      select
        (da.slot_start at time zone 'UTC')::date as day,
        da.area_id,
        sum(da.demand_mw)::double precision as demand_total
      from demand_actuals da
      join requested_areas ra on ra.id = da.area_id
      where da.slot_start >= now() - (p_days::text || ' days')::interval
        and da.demand_mw is not null
      group by 1, 2
    ),
    day_gen as (
      select
        (gma.slot_start at time zone 'UTC')::date as day,
        gma.area_id,
        sum(coalesce(gma.output_mw, 0))::double precision as gen_total
      from generation_mix_actuals gma
      join requested_areas ra on ra.id = gma.area_id
      where gma.slot_start >= now() - (p_days::text || ' days')::interval
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
    order by 1, 2;
  end if;
end;
$$;

grant execute on function region_history(text[], text, int) to anon, authenticated;
