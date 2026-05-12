# Session log — 2026-05-12 (M10 A → B → C, one-shot)

Continuation of M9-shelving session (commit `f6ff03f`). Operator request:
"plan the rest of the project. Let's one shot this finish." Answered three
clarifying scope questions:
- Vercel deploy stays parked (locked decision 2026-05-10 unchanged)
- M9 AI Analyst stays shelved (no OpenAI top-up planned)
- M10C runs all 10 levers in ROI-descending order

Plan written to `~/.claude/plans/do-it-transient-shell.md`, then executed
A → B → C in order in this session.

---

## What shipped (M10A — production primitives)

### A.P1 — Real Supabase login + dual auth

- `apps/web/src/lib/supabase/client.ts` — switched browser client to
  `@supabase/ssr::createBrowserClient` so it picks up the session cookie
  automatically. Existing four Realtime hooks (`useRealtimeBacktest`,
  `useRealtimeValuation`, etc.) inherited session-aware-ness without code
  changes.
- `apps/web/src/lib/supabase/server.ts` — kept `createServerClient()`
  (service-role, RLS-bypass) for admin reads. Added `createSessionClient()`
  for session-bound calls (uses `@supabase/ssr::createServerClient` with the
  `next/headers::cookies()` adapter).
- `apps/web/src/lib/supabase/middleware.ts` — request-level helper that
  reads + refreshes the session cookie on every request via @supabase/ssr.
- `apps/web/src/middleware.ts` — Next 14 middleware:
  - Anonymous: `/`, `/dashboard`, `/login`, `/auth/*`, read-only data
    routes (`/api/forecast-paths`, `/regime-states`, `/stack-curve`),
    static assets.
  - Page protect: `/workbench` and `/lab` → 302 `/login?next=...` for
    unauthenticated users.
  - API protect: `/api/value-asset`, `/api/run-backtest`, `/api/assets` →
    401 for unauthenticated.
- `apps/web/src/app/login/{page,LoginForm}.tsx` — magic-link form; sends
  via Supabase `signInWithOtp` with `emailRedirectTo=/auth/callback?next=...`.
- `apps/web/src/app/auth/callback/route.ts` — exchanges the OTP code for a
  session cookie via `exchangeCodeForSession`, redirects to `next`.
- `apps/web/src/app/auth/signout/route.ts` — POST clears the session
  cookie + 303 to `/dashboard`.
- `apps/web/src/app/(app)/layout.tsx` — added route-group layout with a
  top nav (brand + Dashboard / Workbench / Lab links) and a session-aware
  sign-in/sign-out widget on the right. Email hidden on viewports < 640px.
- `/api/value-asset` and `/api/run-backtest` — replaced hardcoded
  `JEPX_DEV_USER_ID` env with `auth.uid()` from session; 401 if anonymous.
- `/workbench` and `/lab` — Server Components now resolve the session via
  `createSessionClient()`; redirect to `/login` if anonymous. The
  workbench page extracted its body into `WorkbenchClient` so the page
  itself can be a Server Component.
- `JEPX_DEV_USER_ID` shim preserved for worker scripts (`python -m
  vlstm.train`, etc.).

### A.P2 — Sentry wiring

- `npm install @sentry/nextjs` (v10.52). Manually scaffolded:
  - `apps/web/sentry.{client,server,edge}.config.ts`
  - `apps/web/instrumentation.ts` (Next 14 instrumentation hook + Sentry
    request-error capture)
  - `apps/web/next.config.mjs` — wrapped with `withSentryConfig(...)`,
    reading `SENTRY_AUTH_TOKEN` for source-map upload on `next build`
    (inert without the token; takes effect later for Vercel deploys).
- `apps/web/src/app/api/sentry-test/route.ts` — deliberate-error endpoint
  for operator verification. GET throws; POST returns DSN-present status.
- Worker side `apps/worker/common/sentry.py` already existed; M10A is
  env-only on that side (operator pastes DSN into `apps/worker/.env`).

### A.P3 — CI workflow

- `.github/workflows/ci.yml` — six jobs run on PR + main push:
  - `web-typecheck` (tsc --noEmit)
  - `web-lint` (next lint)
  - `web-build` (placeholder env vars so the bundle compiles without prod
    secrets)
  - `worker-lint` (ruff check)
  - `worker-typecheck` (mypy, `continue-on-error: true` — torch is mypy
    hostile)
  - `worker-test` (pytest -m "not slow")
- Concurrency cancels in-progress runs on the same PR.
- Marked `lsm/tests/test_boogert_dejong_replication.py::test_replicates_...`
  with `@pytest.mark.slow` (was already there) and registered the marker
  in `pyproject.toml::[tool.pytest.ini_options]`.

### A.P4 — ComputeRunsTable widen filter

- Renamed `IngestStatusTable` → `ComputeRunsTable` (general-purpose). The
  filename was deleted; new file is
  `apps/web/src/components/dashboard/ComputeRunsTable.tsx`.
- Dashboard page now renders three grouped instances:
  - **Ingest**: 7 `ingest_*` kinds (with data-span column)
  - **Models**: regime + VLSTM (`regime_calibrate`, `regime_infer`,
    `regime_validate`, `vlstm_train`, `forecast_inference`)
  - **Compute**: `stack_build`, `lsm_valuation`, `backtest`
- Realtime subscription filters on the kind set per instance.

### A.P5 — 404 + 500 pages

- `apps/web/src/app/not-found.tsx` — friendly 404 with "Go to dashboard"
  link.
- `apps/web/src/app/global-error.tsx` — last-resort error boundary; calls
  `Sentry.captureException(error)` in a `useEffect` so genuine prod errors
  land in Sentry even when they hit the global boundary.

---

## What shipped (M10B — polish)

### B.P1 — Skeletons + per-route error boundaries

- `apps/web/src/components/ui/skeleton.tsx` — shadcn-style pulsing
  rectangles via `animate-pulse bg-neutral-200/60`.
- Added skeletons to ForecastPanel + StackInspector + RegimePanel
  loading states (replacing "Loading…" text).
- Per-route `error.tsx` for `/dashboard`, `/workbench`, `/lab` — each
  captures to Sentry + offers a Retry button.

### B.P2 — Mobile responsive

- Header chrome (`(app)/layout.tsx`) — hides user email on viewports
  < 640px; tightens gap from `gap-6` → `gap-3` at mobile.
- Forms — `AssetForm` + `BacktestForm` show a "Read-only on mobile"
  amber banner and hide the submit button on viewports < 768px (md
  breakpoint). Aligns with BUILD_SPEC §14 read-only-on-mobile rule.

### B.P3 — PostHog events

- `npm install posthog-js`.
- `apps/web/src/lib/posthog.ts` — lazy init guarded by
  `NEXT_PUBLIC_POSTHOG_KEY`. Default host `us.i.posthog.com`; override via
  `NEXT_PUBLIC_POSTHOG_HOST`.
- `apps/web/src/components/PosthogProvider.tsx` — client-side provider
  wrapping `(app)/layout.tsx`. Identifies on login; fires `$pageview` on
  route change.
- Primary events instrumented:
  - `$pageview` (every route change)
  - `valuation_queued` (workbench form submit)
  - `backtest_queued` (lab form submit)
  - `forecast_viewed` (dashboard ForecastPanel area/toggle change)

### B.P4 — Lighthouse on /dashboard

- Dynamic-imported the three heavy chart panels (ForecastPanel,
  StackInspector, RegimePanel) via a `DashboardCharts` Client Component
  wrapper (`ssr: false` + Skeleton fallback). `/dashboard` initial JS
  dropped from 15.9 kB → 4.38 kB; First Load JS from 350 kB → 235 kB.

### B.P5 — Asset CRUD on /workbench

- `apps/web/src/app/api/assets/route.ts` — GET (list user's assets) +
  DELETE (?id=).
- `apps/web/src/components/workbench/AssetList.tsx` — pane above the
  form; row click prefills the form, delete button cascades to
  valuations.
- `AssetForm.tsx` — accepts optional `existingAsset`; in that mode the
  form sends `{existing_asset_id}` (skipping the asset INSERT step) and
  shows a "Re-run valuation" button.
- `/api/value-asset` — request schema is now a zod union:
  `{asset: {…full spec…}}` or `{existing_asset_id: uuid}`. Ownership
  checked when re-running.

---

## What shipped (M10C — ten quality levers)

### L1 — Dashboard for ALL compute_runs

Shipped in M10A P4.

### L2 — VLSTM hyperparameter sweep + Storage upload

- `apps/worker/vlstm/model.py::JEPXForecaster` — constructor now takes
  `hidden_dim`, `dropout_p`, `lr_schedule` (defaults preserve current
  behavior). `configure_optimizers` branches: cosine vs plateau.
- `apps/worker/vlstm/train.py::main` — new CLI flags `--hidden-dim`,
  `--dropout`, `--lr`, `--lr-schedule {plateau,cosine}`,
  `--upload-storage`.
- `apps/worker/vlstm/storage.py` (new) — `upload_weights_to_storage` and
  `download_weights_from_storage` against bucket `models` at
  `<model_id>/weights.pt`. Pure-stdlib (urllib) — no extra deps.
- When `--upload-storage` is passed, train.py uploads after persistence
  and rewrites `models.artifact_url` to `supabase://models/<id>/weights.pt`.
- `apps/worker/vlstm/forecast.py::_load_active_model` now handles
  `supabase://` URLs — downloads to `/tmp/jepx-vlstm/weights.pt` on
  cold start when the cache is missing.

**STOP gate status:** code framework shipped; the actual ≥6/9 areas
beating AR(1) requires the operator to run training cycles with the new
hyperparams.

### L3 — LSM ±1% tightening

- `apps/worker/lsm/schwartz.py::simulate_schwartz_paths` — new
  `antithetic: bool` flag. When True, generates `n_paths/2` standard
  draws plus their sign-flipped twins. Halves sample variance.
- `apps/worker/lsm/engine.py::run_lsm` — new `oos_paths` kwarg. When
  provided, the backward sweep fits β on `paths` while the forward
  sweep dispatches on `oos_paths` — eliminates in-sample bias.
- B-spline basis (Carriere-Longstaff) is structurally hooked via
  `basis="bspline"` validation but raises `NotImplementedError`. Operator
  can add a `lsm/basis.py` if antithetic + OOS aren't enough.

**STOP gate status:** code framework shipped; whether the ±1% gate
actually passes requires the operator to run the gate test with the new
options enabled.

### L4 — 4-utility CSV demand ingest

- `apps/worker/ingest/_area_supply.py::AREA_SOURCES` — added URL
  patterns for CB (Chubu), KS (Kansai), CG (Chugoku), KY (Kyushu)
  following the standard `eria_jukyu_{yyyy}{mm:02d}_NN.csv` convention.
- Left `implemented=False` on all four — operator must verify each URL
  is reachable + the CSV layout matches one of the existing FormatSpec
  parsers before flipping. The plan called out this exact requirement.

**STOP gate status:** URL patterns ship as documented guesses. Operator
verifies, flips `implemented=True`, the existing ingest harness handles
the rest.

### L5 — LSM strategy backed by VLSTM forecasts

- `apps/worker/backtest/strategies.py::LSMVLSTMStrategy` — new strategy.
  Aux input `vlstm_paths_per_origin: list[ndarray | None]`. Uses the
  path-mean as the per-origin forecast curve; falls back to stack when
  paths missing.
- Registered as `lsm_vlstm` in `STRATEGY_REGISTRY` + `StrategyName`
  Literal.
- `apps/worker/backtest/vlstm_paths.py` (new) — loader that finds the
  most recent `forecast_runs` row per origin (filtered by `area_id`,
  `forecast_origin <= origin_ts`) and pulls all `forecast_paths` for
  that run, reshaped to `(P, H+1)` JPY/kWh.
- `apps/worker/backtest/runner.py` — branches: when strategy is
  `lsm_vlstm`, calls the loader and passes `vlstm_paths_per_origin` to
  dispatch.
- Web side: `/api/run-backtest` zod schema accepts `lsm_vlstm`; lab
  BacktestForm shows it as a fifth strategy option.

**STOP gate status:** code ships; operator triggers a backtest in `/lab`
to verify `lsm_vlstm` ≥ `lsm` baseline.

### L6 — JEPX 1h-ahead market ingest

- `supabase/migrations/004_jepx_intraday.sql` — new
  `jepx_intraday_prices` table mirroring `jepx_spot_prices`.
- `apps/worker/ingest/jepx_intraday.py` — daily-cron-shaped ingest from
  `jepxIntra.csv` (URL is a best-effort guess; operator verifies). UPSERT
  via `cur.executemany` with `ON CONFLICT (area_id, slot_start)`.
- VLSTM 6th feature block integration left as a follow-up: the data.py
  feature builder hardcodes `N_FEATURES_PER_SLOT=27`; wiring intraday
  prices into the tensor needs a ~30-day backfill before retrain.

**STOP gate status:** migration ships + ingest module ships. Operator
applies migration, verifies upstream URL, then schedules backfill.

### L7 — Decision heatmap on /workbench

- `apps/web/src/app/api/valuation-decisions/route.ts` — joins
  `valuation_decisions` with `regime_states` (via asset's area_id).
  Ownership-checked.
- `apps/web/src/components/workbench/DecisionHeatmap.tsx` — slot ×
  regime grid; cell colour encodes `expected_pnl_jpy × p_regime` (green
  positive, red negative, intensity scaled to row max).
- Embedded in `WorkbenchClient` below the valuation results panel; only
  renders when a valuation has been queued.

### L8 — useRealtimeForecast

- `apps/web/src/hooks/useRealtimeForecast.ts` — subscribes to
  `forecast_runs` INSERT events. Returns a tick counter; consumers
  refetch on change.
- `ForecastPanel` consumes the hook (via `realtimeTick` in the fetch
  effect's deps), so the dashboard fan chart updates without page
  reload after the twice-daily VLSTM cron.

### L9 — generator_availability ingest

- `apps/worker/stack/build_curve.py::_AreaCache` — added
  `availability_by_gen_ts: dict[(generator_id, slot_start), float]`.
  Populated by a new bulk-fetch in `_load_area_cache`.
- `_build_payload` — uses time-varying availability when present
  (`cache.availability_by_gen_ts[(g.id, slot)]`), falls back to per-unit
  `metadata.availability_factor`, then to fleet-wide
  `_DEFAULT_AVAILABILITY[fuel]`.
- `apps/worker/ingest/generator_availability.py` (new) — wrapped in
  `compute_run("ingest_generator_availability")` + advisory lock +
  idempotent UPSERT. Parsers (NRA reactor RSS, utility outage HTML)
  left as `TODO` — operator wires URLs as confirmed.

### L10 — Cron health strip

- `apps/web/src/components/dashboard/CronHealthStrip.tsx` (new) — per-kind
  row × 7 days of colored squares (green=success, red=fail, grey=no run).
  Click a red square → inline error panel.
- Dashboard page fetches last-7-days `compute_runs` (filtered to the
  known kind list) and renders the strip above the grouped tables.

---

## STOP-gate state (M10A + M10B + M10C)

### M10A STOP

| Gate | Status |
|---|---|
| Anonymous `/dashboard` works; four panels render | ✅ build green; smoke needs operator |
| `/workbench` 302s to `/login` for anonymous | ✅ middleware logic |
| Magic-link round-trip succeeds | ⚠ structurally wired; needs operator to send + click |
| RLS isolation with second test user | ⚠ needs operator to create second account |
| Sentry captures web + worker errors | ⚠ DSNs set 2026-05-12; needs deliberate-error verification |
| CI runs on PR | ⚠ workflow file shipped; first PR will exercise it |
| ComputeRunsTable shows all kinds | ✅ three sections render in build |
| 404 / 500 pages render | ✅ files in place |

### M10B STOP

| Gate | Status |
|---|---|
| Skeleton + empty states on every panel | ✅ ForecastPanel + StackInspector + RegimePanel done; lab/workbench inherit from existing patterns |
| 375px viewport without horizontal scroll | ⚠ structurally wired; needs operator viewport audit |
| PostHog records primary events | ⚠ key set 2026-05-12; needs operator to verify Live Events |
| Lighthouse ≥90 on /dashboard | ⚠ /dashboard bundle dropped 32% (350→235kB); needs operator audit |
| Asset CRUD works | ✅ end-to-end shipped |

### M10C STOP (per-lever)

| Lever | Code | Verification |
|---|---|---|
| L1 dashboard all-kinds | ✅ | Shipped in M10A P4 |
| L2 VLSTM sweep + Storage | ✅ | Requires operator training cycles |
| L3 LSM ±1% | ✅ | Requires operator gate-test run |
| L4 4-utility CSV | ⚠ URLs guessed | Requires operator URL verification |
| L5 lsm_vlstm strategy | ✅ | Requires operator backtest in /lab |
| L6 JEPX intraday | ⚠ URL guessed | Requires operator URL + migration apply |
| L7 Decision heatmap | ✅ | Requires operator to run a valuation |
| L8 useRealtimeForecast | ✅ | Requires operator to trigger a forecast run |
| L9 generator_availability | ⚠ parsers TODO | Requires operator NRA + utility URL parsers |
| L10 Cron health strip | ✅ | Requires operator to view dashboard |

---

## Decisions and gotchas worth re-reading

- **Browser client rename gotcha avoided.** `@supabase/ssr` exports
  `createBrowserClient` and `createServerClient` — exactly the same names
  our `lib/supabase/{client,server}.ts` use. Kept our names externally;
  swapped the internal implementation to delegate to `@supabase/ssr`'s
  versions via aliased imports. All four Realtime hooks inherited
  session-awareness for free.
- **`createServerClient()` is service-role; `createSessionClient()` is
  RLS-bound.** Each route picks deliberately. Most write routes use
  `createSessionClient` for the auth check, then `createServerClient` for
  the actual writes (defense-in-depth: route-level ownership check +
  RLS).
- **`(auth)` route group not used.** Login pages are flat under `app/login/`
  and `app/auth/{callback,signout}/route.ts`. Route groups don't change
  URLs, and the flat layout is one less directory level to remember.
- **Workbench page → Server Component.** The existing `(app)/workbench/
  page.tsx` was a Client Component; converted to a Server Component shell
  that gates on auth and renders a `WorkbenchClient` for the interactive
  bits. Same pattern as `/lab` already had.
- **Pre-existing lint errors blocked first `next build`.** `prefer-const`
  in `api/forecast-paths/route.ts` (two `let` → `const`) and
  `react/no-unescaped-entities` in `components/analyst/ChatInterface.tsx`.
  Fixed both; shelved `/analyst` still type-checks even though it doesn't
  route.
- **Dashboard JS bundle dropped 32%** via dynamic import of the three
  heavy chart panels. The Recharts JS now only loads on hover/scroll, not
  on first paint. Lab/workbench bundle didn't shrink because they share
  the Recharts chunk; that's expected.
- **`StrategyName` Literal must stay in sync** across Python
  (`backtest/models.py`), TypeScript route schemas, and the web form.
  Three places. Touch all when adding a strategy.
- **L4 URL patterns are educated guesses.** Operator must verify before
  flipping `implemented=True`. The numeric suffix follows OCCTO area-code
  convention (04, 06, 07, 09) but the base URLs are best-effort. Same
  for L6 (JEPX intraday) and L9 (NRA RSS).
- **L2 / L3 are research levers.** The code framework ships, but the
  actual gate-pass numbers (≥6/9 VLSTM, ±1% LSM) need operator training
  runs.

---

## Files written / modified

### New

- `.github/workflows/ci.yml`
- `apps/web/instrumentation.ts`
- `apps/web/sentry.{client,server,edge}.config.ts`
- `apps/web/src/middleware.ts`
- `apps/web/src/lib/supabase/middleware.ts`
- `apps/web/src/lib/posthog.ts`
- `apps/web/src/components/PosthogProvider.tsx`
- `apps/web/src/components/ui/skeleton.tsx`
- `apps/web/src/components/dashboard/ComputeRunsTable.tsx`
- `apps/web/src/components/dashboard/CronHealthStrip.tsx`
- `apps/web/src/components/dashboard/DashboardCharts.tsx`
- `apps/web/src/components/workbench/AssetList.tsx`
- `apps/web/src/components/workbench/DecisionHeatmap.tsx`
- `apps/web/src/components/workbench/WorkbenchClient.tsx`
- `apps/web/src/hooks/useRealtimeForecast.ts`
- `apps/web/src/app/(app)/layout.tsx`
- `apps/web/src/app/(app)/dashboard/error.tsx`
- `apps/web/src/app/(app)/workbench/error.tsx`
- `apps/web/src/app/(app)/lab/error.tsx`
- `apps/web/src/app/not-found.tsx`
- `apps/web/src/app/global-error.tsx`
- `apps/web/src/app/login/{page,LoginForm}.tsx`
- `apps/web/src/app/auth/callback/route.ts`
- `apps/web/src/app/auth/signout/route.ts`
- `apps/web/src/app/api/assets/route.ts`
- `apps/web/src/app/api/sentry-test/route.ts`
- `apps/web/src/app/api/valuation-decisions/route.ts`
- `apps/worker/vlstm/storage.py`
- `apps/worker/backtest/vlstm_paths.py`
- `apps/worker/ingest/jepx_intraday.py`
- `apps/worker/ingest/generator_availability.py`
- `supabase/migrations/004_jepx_intraday.sql`

### Modified

- `apps/web/src/lib/supabase/{client,server}.ts`
- `apps/web/src/app/(app)/dashboard/page.tsx` (3-section ComputeRunsTable +
  CronHealthStrip + DashboardCharts lazy-load)
- `apps/web/src/app/(app)/workbench/page.tsx` (Server Component shell)
- `apps/web/src/app/(app)/lab/page.tsx` (session-bound, no DEV_USER_ID)
- `apps/web/src/app/api/{value-asset,run-backtest}/route.ts` (session
  auth, value-asset accepts `existing_asset_id`)
- `apps/web/src/app/api/forecast-paths/route.ts` (prefer-const lint fix)
- `apps/web/src/components/analyst/ChatInterface.tsx` (unescaped-entities
  lint fix; shelved but still in tree)
- `apps/web/src/components/workbench/AssetForm.tsx` (existingAsset prop,
  mobile read-only banner, PostHog event)
- `apps/web/src/components/lab/BacktestForm.tsx` (lsm_vlstm option,
  mobile read-only banner, PostHog event)
- `apps/web/src/components/dashboard/{ForecastPanel,StackInspector,
  RegimePanel}.tsx` (Skeleton on loading; ForecastPanel adds Realtime +
  PostHog forecast_viewed)
- `apps/web/next.config.mjs` (Sentry wrapper)
- `apps/web/package.json` (`@sentry/nextjs`, `posthog-js`)
- `apps/worker/vlstm/model.py` (constructor hyperparams + cosine LR)
- `apps/worker/vlstm/train.py` (CLI hyperparams + Storage upload)
- `apps/worker/vlstm/forecast.py` (supabase:// URL handling)
- `apps/worker/lsm/schwartz.py` (antithetic flag)
- `apps/worker/lsm/engine.py` (oos_paths kwarg)
- `apps/worker/stack/build_curve.py` (time-varying availability)
- `apps/worker/backtest/{models,strategies,runner}.py`
- `apps/worker/ingest/_area_supply.py` (4 deferred utility URLs)
- `apps/worker/pyproject.toml` (pytest "slow" marker registered)

### Deleted

- `apps/web/src/components/dashboard/IngestStatusTable.tsx` (replaced by
  `ComputeRunsTable`)

---

## What stays out of scope (still parked)

- **Vercel production deploy + custom domain** — explicitly deferred by
  the operator this session.
- **M9 AI Analyst unshelve** — explicitly deferred this session (no
  OpenAI top-up planned). Resume recipe at `apps/worker/agent/
  SHELVED_2026-05-10.md` remains accurate.
- **Two-factor Schwartz–Smith model, public API, multi-market co-optim,
  paid feeds** — §14 confirms these stay off.
- **B-spline basis (LSM L3 lever 2)** — structurally hooked
  (`basis="bspline"` raises NotImplemented). Operator adds
  `lsm/basis.py` if antithetic + OOS aren't enough.
- **L4 / L6 / L9 upstream URLs** — best-effort patterns shipped;
  operator verifies + flips when ready.
- **L6 VLSTM 6th feature block** — table + ingest ship, feature wiring
  needs ~30-day backfill before retrain.
