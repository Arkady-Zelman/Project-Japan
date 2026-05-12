-- ============================================================
-- 006_demo_examples.sql
-- ============================================================
-- Adds a public-demo lane to assets / valuations / backtests so the portfolio
-- pages (/workbench, /lab) can render a daily-refreshed example without an
-- authenticated user. Demo rows are tagged is_demo=TRUE and have user_id NULL
-- (and portfolio_id NULL on assets), bypassing the auth.users FK.
--
-- Read-side: anon role gets a SELECT policy for is_demo=TRUE rows; the
-- existing user-scoped policies stay untouched, so authenticated user data
-- remains private.
-- ============================================================

-- ---------- assets ----------

alter table assets
  add column is_demo boolean not null default false;

alter table assets alter column portfolio_id drop not null;
alter table assets alter column user_id drop not null;

alter table assets add constraint assets_user_xor_demo check (
  (is_demo = true and user_id is null and portfolio_id is null)
  or (is_demo = false and user_id is not null and portfolio_id is not null)
);

-- Exactly one demo asset can exist at a time (idempotent upsert anchor).
create unique index assets_only_one_demo
  on assets ((1)) where is_demo = true;

create policy assets_demo_anon_read on assets
  for select to anon using (is_demo = true);
create policy assets_demo_authn_read on assets
  for select to authenticated using (is_demo = true);

-- ---------- valuations ----------

alter table valuations
  add column is_demo boolean not null default false;

alter table valuations alter column user_id drop not null;

alter table valuations add constraint valuations_user_xor_demo check (
  (is_demo = true and user_id is null)
  or (is_demo = false and user_id is not null)
);

create index valuations_demo_recent
  on valuations (created_at desc) where is_demo = true;

create policy valuations_demo_anon_read on valuations
  for select to anon using (is_demo = true);
create policy valuations_demo_authn_read on valuations
  for select to authenticated using (is_demo = true);

-- Decisions cascade visibility through the valuation row — anon can read a
-- valuation_decisions row iff its parent valuation is a demo.
create policy valuation_decisions_demo_anon_read on valuation_decisions
  for select to anon using (
    exists (
      select 1 from valuations v
      where v.id = valuation_decisions.valuation_id and v.is_demo = true
    )
  );
create policy valuation_decisions_demo_authn_read on valuation_decisions
  for select to authenticated using (
    exists (
      select 1 from valuations v
      where v.id = valuation_decisions.valuation_id and v.is_demo = true
    )
  );

-- ---------- backtests ----------

alter table backtests
  add column is_demo boolean not null default false;

alter table backtests alter column user_id drop not null;

alter table backtests add constraint backtests_user_xor_demo check (
  (is_demo = true and user_id is null)
  or (is_demo = false and user_id is not null)
);

create index backtests_demo_recent
  on backtests (created_at desc) where is_demo = true;

create policy backtests_demo_anon_read on backtests
  for select to anon using (is_demo = true);
create policy backtests_demo_authn_read on backtests
  for select to authenticated using (is_demo = true);
