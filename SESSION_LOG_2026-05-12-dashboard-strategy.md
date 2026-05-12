# Session log — 2026-05-12 (dashboard overhaul + Strategy tab + 9-utility ingest)

Continuation of M10 (committed `f6ff03f` agent-shelving + a follow-up commit that landed the M10A/B/C functional polish). Started with the post-M10 working tree at "engine works, UI looks like a wireframe", finished with the operator's signed-off "I like what we have at the moment" — full dashboard redesign, Japan map, BoS Strategy tab, and a proper 9-utility ingest pipeline.

---

## What shipped

### 1. Tabbed dashboard with Japan regional map
The single-column `/dashboard` got rebuilt around a `TabBar`: **Map** (default) / **Strategy** / **Forecast** / **Stack** / **Regime** / **Health**. Tab state in `?tab=…`; everything but the active tab lazy-loads.

- `(app)/dashboard/page.tsx` is now a thin server shell that hands compute-run aggregates to a `DashboardClient` Client Component.
- Page-level chrome: `PageHeader` with title + supporting paragraph + 4-metric strip (system demand, gen, VRE share, Tokyo JEPX) + a top-right actions cluster (`Updated HH:MM UTC` · `Refresh ↻` · status pill `Live` / `Syncing` / `No data` / `Error`).
- `JapanRegionalMap` renders a real cartographic SVG of the 9 utility regions (generated build-time via `apps/web/scripts/build-japan-paths.mjs` → projected with d3-geo, integer-coord rounded, 91 KB instead of 1.9 MB). Hover → stroke highlight + tooltip; click → expand `RegionDetail` accordion below the map.
- Metric toggle on the map: **VRE share** (default, green ramp), **Balance**, **JEPX price**.

### 2. Strategy tab — Basket of Spreads (BoS) methodology
New section directly informed by Baker, O'Brien, Ogden, Strickland, *"Gas storage valuation strategies"*, Risk.net Nov 2017 (PDF on operator's desktop). Builds the optimal portfolio of calendar spread options on half-hour slot forwards, subject to BESS power + capacity constraints.

Four panels stacked:
1. **Today's schedule** — plain-English summary ("Charge X MWh in N windows at ¥… ; discharge Y MWh in M windows at ¥…"), colour-coded horizontal timeline strip (one cell per half-hour), per-window list with start/end times and avg price.
2. **Metric cards** — BoS total value, intrinsic, extrinsic, per-kWh of capacity.
3. **Physical profile** — half-hourly charge bars (green, up) / discharge bars (red, down) / inventory line (blue).
4. **Expected P&L over time** — cumulative cashflow line + dashed cum-charge-spend (red) and cum-discharge-revenue (green); legend shows realised vs intrinsic vs total-BoS targets.
5. **Basket composition table** — per-CSO: charge slot, discharge slot, MW volume, spread (¥/kWh), σ_spread, intrinsic / extrinsic / total JPY. Sorted by total value descending.

Toolbar lets the operator pick **VLSTM forecast** (default — pulls the latest `forecast_runs` for the asset's area, paginates `forecast_paths`, computes mean+stdev across the 1000-path ensemble) or **Realised (28d)** (bucketed by weekday × half-hour) and a horizon (1 day → 7 days). Pure TypeScript engine in `lib/bos-strategy.ts`; greedy fill by per-MWh value (matches LP optimum for continuous BESS volumes).

### 3. Proper 9-utility data ingest
Started the day with 5 utilities ingesting (TK / HK / TH / HR / SK) and the 4 deferred (CB / KS / CG / KY) on `synthesize_demand` fallback. Ended with **all 9 implemented + verified + backfilled 30 days**.

URLs discovered by reverse-engineering each utility's frontend JavaScript:
| Code | Real URL | Format | Method |
|---|---|---|---|
| CB Chubu | `powergrid.chuden.co.jp/denkiyoho/resource/php/getCsv.php?file=eria_jukyu_{YYYYMM}_04.csv` | V2 (22 cols) | PHP proxy in `get-data.js` |
| KS Kansai | `kansai-td.co.jp/interchange/denkiyoho/area-performance/eria_jukyu_{YYYYMM}_06.csv` | V1 (20 cols) | filename list at `filelist.json` |
| CG Chugoku | `energia.co.jp/nw/jukyuu/sys/eria_jukyu_{YYYYMM}_07.csv` | V2 (22 cols) | filename built in `script_eriajukyu_1.js` |
| KY Kyushu | `kyuden.co.jp/td_area_jukyu/csv/eria_jukyu_{YYYYMM}_09.csv` | V1 (20 cols) | direct |

**Tohoku publishes monthly only at fiscal-year boundaries** (FY2025 went up to 202603, then nothing). They publish a daily realtime CSV — added `daily_url_pattern` to `UtilitySource` + a daily-fallback branch in `fetch_for_area` that fires whenever the monthly 404s for a requested month. TH now lands within 24 h of the slot date.

After backfill all 9 areas have demand + gen-mix through 2026-05-12.

### 4. Smarter snapshot-slot selection
Map's first paint used to be "absolute latest demand_actuals slot" which was usually missing HK/TH (1-2 day publication lag). Now uses a Postgres function `latest_full_coverage_slot(lookback_days, min_areas)` (migration `005_latest_coverage_slot.sql`) that joins demand_actuals with generation_mix_actuals and returns the latest slot where:
- ≥ `min_areas` areas have non-null demand_mw, AND
- ≥ min(9, 8) areas have non-zero gen-mix.

Walk-back ladder in `/api/regional-balance`: try 9 → 8 → 7 → fall through to absolute latest. Result with current data: snapshot is 2026-05-10 14:30 UTC, 9/9 demand + 9/9 gen-mix.

### 5. Stack-Inspector slot dropdown filter
Date picker used to expose 48 half-hour values, of which most slots had no `stack_curves` row. New `/api/stack-curve/slots?area=TK&date=YYYY-MM-DD` returns only the timestamps with data; StackInspector refetches the list on (area, date) change and auto-snaps `slot` if the current value drops out.

### 6. Aesthetic + behavioural polish
- Forced **dark mode** at the `<html className="dark">` level — light-mode tokens stay defined but unused.
- Page-header chrome treatment unified across `/dashboard`, `/workbench`, `/lab`, `/login`.
- **Time-axis ticks vertical** on every chart: ForecastPanel (HH:MM), RegimePanel (MM-DD HH:MM), StrategyTab × 2 (HH:MM), ValuationResults × 3 (HH:MM), BacktestResults equity curve (MM-DD HH:MM). All `angle={-90}`, `textAnchor="end"`, `height ≥ 56–64`. No more overlapping labels.
- Light cleanup: removed the synthetic-test red squares I'd left in `compute_runs` (`lsm_valuation` + `backtest` rows with zero-UUID errors).

---

## STOP-gate state

| Surface | Status |
|---|---|
| `/dashboard` first paint (anonymous) | ✅ 9 regions populated, Live pill, hero metrics live |
| `/dashboard?tab=strategy` | ✅ BoS engine returns valid basket against VLSTM forecast; explanation + chart + table all render |
| `/dashboard?tab=stack` | ✅ Slot dropdown filtered to slots with data |
| `/dashboard?tab=forecast` / `regime` | ✅ Charts render with vertical ticks |
| `/dashboard?tab=health` | ✅ All `compute_runs` kinds visible; cron health strip clean |
| `/workbench`, `/lab` | ✅ Aesthetic consistent; charts share tick treatment |
| 9-utility ingest live data | ✅ All 9 areas fresh through 2026-05-12 |
| Modal deploy | ⚠ Still on v4 (2026-05-10); today's `_AREA_SOURCES` updates + `daily_url_pattern` only running against live DB because `modal run` uses ephemeral dev-mode functions. Needs `modal deploy` to take effect for the next cron fire. |
| OpenAI / M9 unshelve | ⚠ Still parked |

---

## Decisions and gotchas worth re-reading

- **Next 14 fetch cache hides fresh Supabase rows even with `force-dynamic`.** Symptom: API kept returning "yesterday's slot" after ingest. Two-layer fix needed: `revalidate=0 + fetchCache=force-no-store` at the route level **and** `cache: "no-store"` on the underlying fetch inside `createServerClient`. Both required. SESSION_LOG_2026-05-12-M10.md was about M10 functionality; this caching bite was specifically about the regional-balance route.
- **Supabase REST default row cap = 1000.** Aggregation queries that need to look at >1000 rows can't be expressed in PostgREST GROUP BY. Use a SQL function (`.rpc(...)`) instead. `latest_full_coverage_slot` is the canonical example.
- **React Strict Mode kills naïvely-named Realtime channels.** Six Realtime hook sites needed a per-mount `${Math.random().toString(36).slice(2)}` suffix to survive the dev-mode double-effect. Symptom was `cannot add postgres_changes callbacks for realtime:X after subscribe()`.
- **Supabase generated DB types don't include `latest_full_coverage_slot`.** Cast `supabase.rpc as unknown as (fn: string, args) => …` to call it without regenerating types. Cleaner than re-running the codegen each time a function lands.
- **`data-horizontal:flex-col` is not a default Tailwind variant.** The shadcn `Tabs` primitive looked OK in isolation but rendered tabs and panels SIDE-BY-SIDE because the variant silently did nothing. Replaced with a hand-rolled `TabBar` (plain horizontal strip + content panel below). Lesson: don't trust shadcn-pasted CSS variants without `data-[orientation=horizontal]:…` form.
- **`forecast_paths.path_id`, not `path_index`.** First pass of the BoS API was using the column names from VLSTM training code, which differ from the actual DB schema. Always grep the migration before composing a Supabase query.
- **Tohoku's monthly CSV publishes ONCE per fiscal-year.** Their data is otherwise current via a separate daily-CSV endpoint. The `daily_url_pattern` field on `UtilitySource` is now the right place for any utility that decouples daily-realtime from monthly-archive cadence.
- **The Tokyo-prefecture-only Shizuoka split is unresolved.** Per the map plan, Shizuoka goes whole to TK; in reality the eastern slice belongs to TK and western to CB. Visually noticeable on the map for the prefecture's south coast. Parked.
- **The map's integer-coord rounding** brought the path artefact from 1.9 MB → 91 KB. dt=0.1° at 800 viewBox = ~0.1px — invisible at any sane render size but worth knowing if someone ever wants to zoom past 4×.
- **One-shot preference saved to memory** (`feedback_one_shot_plans.md`): when operator says "one shot", plan as a single phase with one STOP at the end. The earlier multi-phase plan got rejected with this instruction.

---

## Files written / modified this session

### New (web)
- `apps/web/scripts/build-japan-paths.mjs` + generated `apps/web/src/lib/japan-region-paths.ts`
- `apps/web/src/lib/{fuel-colors,bos-strategy}.ts`
- `apps/web/src/app/api/regional-balance/route.ts`
- `apps/web/src/app/api/stack-curve/{latest,slots}/route.ts`
- `apps/web/src/app/api/bos-strategy/route.ts`
- `apps/web/src/hooks/useRealtimeRegionalBalance.ts`
- `apps/web/src/components/ui/{page-header,metric-card,section,tab-bar}.tsx`
- `apps/web/src/components/dashboard/{JapanRegionalMap,RegionDetail,ComputeRunsTable,CronHealthStrip,DashboardClient,StrategyTab,types}.tsx`
- Per-route `error.tsx` for `/dashboard`, `/workbench`, `/lab`
- `apps/web/src/components/workbench/{AssetList,DecisionHeatmap,WorkbenchClient}.tsx`
- `apps/web/sentry.{client,server,edge}.config.ts` + `instrumentation.ts` (from M10A P2)

### Modified
- `apps/web/src/middleware.ts` — anon paths + auth-gated paths extended
- `apps/web/src/lib/supabase/{client,server,middleware}.ts` — session-aware browser/server clients, `cache: no-store` global fetch on service client
- `apps/web/src/app/layout.tsx` — `<html className="dark">`
- `apps/web/src/app/(app)/{layout,dashboard,workbench,lab}/page.tsx`
- `apps/web/src/app/login/{page,LoginForm}.tsx`
- `apps/web/src/app/api/{value-asset,run-backtest,assets,valuation-decisions}/route.ts` — session-bound auth
- `apps/web/src/components/dashboard/{StackInspector,ForecastPanel,RegimePanel}.tsx` — tab integration + vertical-tick X-axes
- `apps/web/src/components/lab/{LabClient,BacktestForm,BacktestResults}.tsx`
- `apps/web/src/components/workbench/{AssetForm,ValuationResults}.tsx`
- `apps/web/next.config.mjs` — `withSentryConfig` wrap
- `apps/web/package.json` — `@sentry/nextjs`, `@supabase/ssr`, `posthog-js`, dev-deps `d3-geo` + `topojson-client`

### New (worker)
- `apps/worker/vlstm/storage.py` — Supabase Storage upload/download of `weights.pt`
- `apps/worker/backtest/vlstm_paths.py` — loader for VLSTM-driven LSM backtest
- `apps/worker/ingest/{jepx_intraday,generator_availability}.py`
- `supabase/migrations/{004_jepx_intraday,005_latest_coverage_slot}.sql`

### Modified (worker)
- `apps/worker/ingest/_area_supply.py` — verified URLs for CB/KS/CG/KY + `daily_url_pattern` + per-day fallback branch for TH
- `apps/worker/vlstm/{model,train,forecast}.py` — hyperparam-aware constructor, Storage upload flag, `supabase://` URL handling
- `apps/worker/lsm/{engine,schwartz}.py` — antithetic variates + `oos_paths` kwarg
- `apps/worker/backtest/{models,strategies,runner}.py` — `lsm_vlstm` registered + auto-loaded
- `apps/worker/stack/build_curve.py` — time-varying `generator_availability` lookup
- `apps/worker/modal_app.py` — `models_weekly` bundled cron replacing the standalone regime weekly
- `apps/worker/pyproject.toml` — `slow` pytest marker registered

### Memory
- `~/.claude/projects/.../memory/feedback_one_shot_plans.md` — saved the bundled-execution preference

### Cleanup
- Deleted `apps/web/src/components/dashboard/{IngestStatusTable,DashboardCharts}.tsx` (superseded by `ComputeRunsTable` + per-tab dynamic imports inside `DashboardClient`)

---

## Out of scope (still parked)

- **Vercel production deploy + custom domain** — still localhost-only per the M10 plan lock.
- **M9 AI Analyst unshelve** — depends on OpenAI credit top-up. `apps/worker/agent/SHELVED_2026-05-10.md` resume recipe still accurate.
- **Modal redeploy** — last deploy was 2026-05-10 v4. Today's `_area_supply.py` + `models_weekly` etc. won't fire on cron until `npm run worker:modal -- deploy modal_app.py`. The 4-new-utility URLs work today because `ingest_backfill` ran via `modal run` which deploys ephemerally.
- **Shizuoka prefecture's Fuji-river split** — whole prefecture goes to TK on the map. Cosmetic.
- **VLSTM forecast horizon mismatch** — current twice-daily run produces 48 slots = 24h. Strategy tab "horizon = 7 days" option does ~336 slot pairs but only 48 slots exist in `forecast_paths` so the basket truncates. Either extend the forecast horizon (training change) or warn in the UI.
- **VLSTM weights re-train against the latest data** — Modal `models_weekly` cron will trigger this Sunday 18:00 UTC; first run still pending.
- **Stack model run against 2026-05** — only TK has backfill through 2024-04. `stack_run_daily` cron fires nightly going forward; backfill of 2024-04 → 2026-05 for all 9 areas hasn't been run yet.

---

## Operator-facing verification checklist

1. **`/dashboard`** opens on the Map tab; hero shows live system totals; pill says `Live` (green).
2. Map renders **9 colour-encoded regions**; metric toggle (VRE / Balance / Price) re-shades them.
3. Click any region → accordion expands with donut + breakdown + "See stack curve →" link.
4. `/dashboard?tab=strategy` opens; toolbar lets you toggle VLSTM ↔ Realised forward curve; Recompute spins ↻.
   - Schedule panel reads: "Charge X MWh in N windows at ¥… ; discharge Y MWh in M windows at ¥…".
   - Physical profile shows half-hourly bars, vertical X-axis ticks, every label legible.
   - Expected P&L curve dips during charge windows, rises during discharge windows, ends at intrinsic target.
   - Basket table shows the per-CSO breakdown.
5. `/dashboard?tab=stack` → date picker shows only dates with data; slot dropdown shows only half-hours with curves.
6. `/dashboard?tab=forecast` and `regime` charts render with rotated time labels, no overlap.
7. `/dashboard?tab=health` shows cron health strip + three grouped compute-run tables.
8. `/workbench` valuation result charts show vertical time labels.
9. `/lab` equity curve chart shows vertical time labels.
10. Hard-reload at any time → still shows same slot (cache buster + no-store works).

---

## Next session candidates

- **Modal redeploy** so the 4 new utilities ingest on schedule, not just on backfill.
- **Stack model backfill** for the 9 areas over 2024-04 → 2026-05 so the Stack tab is populated for non-TK regions.
- **Lever 2 (VLSTM hyperparameter sweep)** with the longer-history dataset now available. Once gate is ≥6/9, push the result; that also feeds the BoS extrinsic values via the forecast-path stdev.
- **Vercel production deploy** when ready.
- **M9 unshelve** when OpenAI credits land.
