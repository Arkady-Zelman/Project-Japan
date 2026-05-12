-- M10C L6: JEPX 1h-ahead (intraday) market.
-- Schema mirrors jepx_spot_prices for the day-ahead market.

create table if not exists jepx_intraday_prices (
  area_id uuid not null references areas(id),
  slot_start timestamptz not null,
  slot_end timestamptz not null,
  price_jpy_kwh numeric(10,4),
  volume_mwh numeric(12,2),
  source text not null default 'japanesepower_csv',
  primary key (area_id, slot_start)
);
create index if not exists jepx_intraday_prices_slot_idx on jepx_intraday_prices (slot_start);
