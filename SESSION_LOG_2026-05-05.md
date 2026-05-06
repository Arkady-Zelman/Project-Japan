# Session log — 2026-05-04 → 2026-05-05

Continuation of `SESSION_LOG_2026-05-04.md`. Started with three commits landing M1+M2 in git history; ended with **Milestone 3 (Tier 1 ingest) shipped**, 540K + 525K + 233K rows in cloud, all six ingest sources running on Modal cron, dashboard live, and one architectural decision (Supabase Pro upgrade) along the way.

---

## What shipped (M3)

### Plan + ground rules
- Plan-mode session locked five decisions before any code: shared `common/db.py` helper, pandas (not polars), assistant-proposed backfill orchestration (single Modal `ingest_backfill` + same code path for daily and historical), shadcn deferred to M4. BUILD_SPEC §2 got a dated paragraph noting the shadcn deferral isn't a permanent skip.

### `apps/worker/common/`
Five small modules, each with one job. New rule baked into `apps/worker/CLAUDE.md::Ingest discipline`: every Postgres-touching path in the worker uses these helpers, no exceptions.

| File | Purpose |
| --- | --- |
| `common/db.py` | `connect()` — `psycopg.Connection` pre-configured with `prepare_threshold=None`. One place to set the flag, no rediscoveries. Loads `apps/worker/.env` once on first call. |
| `common/audit.py` | `with compute_run("ingest_fx") as run:` — inserts `compute_runs` row at start, updates on exit with `status` + `duration_ms` + `error` + JSON metadata. Symmetric, exception-safe. |
| `common/lock.py` | `advisory_lock(cur, "ingest_fx")` — `pg_advisory_xact_lock(hashtext(name))`. Auto-released with the transaction. Per spec §7.2 line 845. |
| `common/retry.py` | `@retry_transient` — tenacity, 5 attempts, exponential backoff with jitter. Retries on transient HTTP/DB errors only; 4xx and `IntegrityError` get re-raised. |
| `common/sentry.py` | `init_sentry()` — no-op if `SENTRY_DSN` unset. Each ingest job tags with `source=ingest_<name>` for filterability. |

### Six ingest sources — `apps/worker/ingest/`
Each exports `def ingest(start: date, end: date) -> IngestResult`. Decorated with `@compute_run` and wrapped in `advisory_lock`. Pydantic validates per-row before write.

| File | Source | Target | Notes |
| --- | --- | --- | --- |
| `ingest/jepx_prices.py` | japanesepower.org `jepxSpot.csv` | `jepx_spot_prices` | Wide CSV (40 MB) → pandas melt → long. Half-hourly, day-ahead auction. |
| `ingest/demand.py` | japanesepower.org `demand.csv` | `demand_actuals` | Hourly. Source last updated 2024-03-31; `_upstream_latest()` reports the freshest date dynamically — no hardcoded cutoff. |
| `ingest/generation_mix.py` | TEPCO per-utility CSVs (see below) | `generation_mix_actuals` | TK area only. Dual URL format. |
| `ingest/weather.py` | Open-Meteo `/archive` | `weather_obs` | 9 area centroids. Hourly. `wind_speed_unit=ms` so we don't have to convert. |
| `ingest/fx.py` | api.frankfurter.dev | `fx_rates` | USDJPY, business days only (weekends are correctly empty). |
| `ingest/holidays.py` | `holidays` Python pkg | `jp_holidays` | Reuses `seed.load_reference.build_holidays`. Annual cron + on-demand. |

Plus `ingest/__main__.py` (`python -m ingest <source> --start ... --end ...`) for development without Modal round-trips, and `ingest/_areas.py` mapping JEPX area codes ↔ japanesepower.org column names ↔ weather centroid lat/lon pairs.

### Modal scheduling — `apps/worker/modal_app.py`
- Image bumped to Python 3.12 per spec §11. Pip-installs all M3 deps directly (so the Modal image doesn't need pyproject.toml resolution). `add_local_python_source("common", "ingest", "seed")` makes the worker packages available inside containers.
- `Modal.Secret.from_name("jepx-supabase")` injects every env key the worker needs. Created via `modal secret create jepx-supabase --from-dotenv .env`.
- Three new functions:
  - `ingest_daily()` — `Cron("0 21 * * *")` UTC = 06:00 JST. Fans out to all 6 sources for `[yesterday, today)`. Per-source try/except so one failure doesn't abort the rest; audit + lock are inside each source so they handle their own lifecycle.
  - `ingest_holidays_annual()` — `Cron("5 0 1 1 *")`. Refreshes the next 8 years of holidays.
  - `ingest_backfill(start_iso, end_iso, sources="")` — on-demand, no schedule. `sources` is a comma-separated string (Modal's CLI doesn't accept `list[str]` annotations).

### Dashboard — `apps/web/src/app/(app)/dashboard/page.tsx`
Replaces the M1 placeholder. Server Component does the initial fetch of `compute_runs` + per-target data spans; Client Component (`IngestStatusTable`) subscribes to Supabase Realtime on `compute_runs` and patches the table when new ingest rows land. Hand-rolled Tailwind v3 utilities; no shadcn.

`apps/web/next.config.mjs` got two adjustments:
- `dotenv` loads the repo-root `.env.local` (Next.js's default search is `apps/web/`).
- `transpilePackages: ["@jepx/shared-types"]` so the workspace package resolves through the linked symlink.

`apps/web/src/lib/supabase/{server,client}.ts` are the typed client wrappers.

### Backfill execution
- **First pass** (5-year, 2020-01-01 → 2026-04-30): ran on Modal in ~8 minutes. Result: 1.1M jepx prices, 335K demand (capped 2024-03-31), 443K weather (one Kyushu month hit Open-Meteo's 429), 1622 fx, ~430K generation_mix (annual format only).

### Sentry
- Modal Secret refreshed with `SENTRY_DSN`. Local test exception emitted with tag `test_marker=m3-sentry-verification` and `source=ingest_test`. Confirmed ingestion path; cron failures will surface there going forward.

---

## The Free-tier wall + Pro upgrade

Mid-session the cloud DB went into platform-side read-only mode. Diagnostic showed `default_transaction_read_only=on` (source: `configuration file` — set by Supabase, not user-configurable) and `db_size=594 MB` against the free-tier 500 MB ceiling. Even the dashboard SQL Editor was rejected with `ERROR: 25006: cannot execute DELETE in a read-only transaction`.

**Catch-22:** writes blocked because over quota → can't delete to drop below quota.

Decision: **upgraded to Supabase Pro** (8 GB disk, $25/month). Two open paths were considered:
- A. Pay → cleanup → downgrade ($1-3 prorated).
- B. Provision a fresh free-tier project, abandon the over-quota one, re-run a slim backfill.

User picked the Pro upgrade to keep the existing data intact.

After upgrade:
- Disk allocation went from ~500 MB to 8 GB. **The platform-side `default_transaction_read_only=on` flag remained**, but Supabase's documented override flow worked: in the SQL Editor, run `set session characteristics as transaction read write;` then `vacuum;` then `set default_transaction_read_only = 'off';`. After that, writes work everywhere — though the dashboard banner can stay stuck on "read-only" UI cosmetic for some time. **Pause + resume the project, or open a Supabase support ticket, to force the banner to clear.**

### Cleanup operation (post-upgrade)
Original plan was: trim to 3 years (option A) + drop SYS rows (option C). User confirmed both apply.

```sql
delete from jepx_spot_prices       where slot_start < '2023-01-01'; -- 526,080 rows
delete from demand_actuals         where slot_start < '2023-01-01'; -- 236,736
delete from weather_obs            where ts         < '2023-01-01'; -- 210,432
delete from fx_rates               where ts         < '2023-01-01'; -- 773
delete from generation_mix_actuals where slot_start < '2023-01-01'; -- 210,432
delete from jepx_spot_prices where area_id = (select id from areas where code='SYS'); -- 58,368
```

Plain `VACUUM ANALYZE` after — not `VACUUM FULL`. Pro tier has 8 GB headroom, so reclaiming pages to OS is unnecessary; the freed space inside the table gets reused by subsequent inserts.

---

## generation_mix — biggest M3 reshape

Spec originally called for "japanesepower.org HH Data" as the v1 source. Recon during M3 found that japanesepower.org publishes spot/intraday/demand/weather only — **no fuel-mix CSV exists there**. The rendered chart on japanesepower.org's regional pages comes from data we can't access.

Replacement: **per-utility "エリア需給実績" (area supply-demand record) CSVs**, the official TSO publications consumed by OCCTO for cross-area aggregation. URL patterns documented in BUILD_SPEC §7.1.1 for all 9 utilities; M3 implements TEPCO (TK area) only; v2 follow-up rolls out the other 8 mechanically.

### TEPCO has two URL patterns

| Format | URL pattern | Granule | Coverage | Thermal split |
| --- | --- | --- | --- | --- |
| Annual | `tepco.co.jp/forecast/html/images/area-{fy}.csv` | Hourly | FY2016 → FY2023 (Mar 2024) | Single `火力` column |
| Monthly | `tepco.co.jp/forecast/html/images/eria_jukyu_{yyyy}{mm:02d}_03.csv` | 30-min | FY2023 (Feb 2024) onwards | LNG / coal / oil / その他 split + 蓄電池 (battery) column |

The monthly format is strictly richer (more granularity + finer fuel split + already in MW, no `万kWh` ÷10 conversion needed). Parser tries monthly per-month first, falls back to annual per-fiscal-year for months not covered.

After re-running the focused generation_mix backfill (2023-01-01 → 2026-05-01):

```
genmix_rows: 539,832
genmix_min:  2023-01-01
genmix_max:  2026-04-30

Per-fuel:               monthly era    annual era
  battery                36,462         7,314
  biomass                36,462        14,601
  coal                   36,462         7,314
  geothermal             36,462        14,601
  hydro                  36,462        14,601
  lng_ccgt               36,462        14,601
  nuclear                36,462        14,601
  oil                    36,462         7,314
  pumped_storage         36,462        14,601
  solar                  36,462        14,601
  wind                   36,462        14,601
```

`battery`, `coal`, `oil` only appear in monthly-era rows because the annual format lumps everything into the single `火力` bucket — that's why nuclear/hydro/etc. have ~2× the annual-era rows of battery/coal/oil.

### Spec change (committed)
- BUILD_SPEC §7.1 row for `ingest_generation_mix` updated to point at the per-utility scraper.
- New §7.1.1 added with the full 9-utility URL table, dated **2026-05-04**, explaining why the spec moved off the japanesepower.org plan.

---

## Final state

| Surface | State |
| --- | --- |
| Cloud DB size | 644 MB / 8 GB Pro = 8% used |
| jepx_spot_prices | 525,312 rows, 2023-01-01 → 2026-04-30, 9 areas (no SYS) |
| demand_actuals | 98,415 rows, 2023-01-01 → 2024-03-31 (upstream stale) |
| weather_obs | 233,496 rows, 2023-01-01 → 2026-04-30 |
| fx_rates | 849 rows, 2023-01-02 → 2026-04-30 |
| generation_mix_actuals | 539,832 rows, 2023-01-01 → 2026-04-30, TEPCO/TK only |
| jp_holidays | 222 rows, 2020-2027 |
| data_dictionary | 226 rows |
| Modal cron | `ingest_daily` at 06:00 JST + `ingest_holidays_annual` Jan 1 + on-demand `ingest_backfill` |
| Dashboard | http://localhost:3000/dashboard, 6 sources OK, Realtime auto-refresh |
| Sentry | Initialised, test event delivered |
| Modal Secret | `jepx-supabase` populated from `.env` |

---

## Decisions and gotchas worth re-reading

- **`prepare_threshold=None` is required everywhere.** Supabase's transaction pooler (port 6543) rejects PREPARE. Without the flag, `executemany()` collides on `_pg3_0`. `common.db.connect()` handles this in one place.
- **The pooler URL has `<role>.<project-ref>` as the username**, not just `<role>`. Direct (port 5432) connections use just `<role>`. Lots of confusion possible if env URLs are constructed by hand.
- **`<role>.<project-ref>` host is `aws-1-ap-northeast-1.pooler.supabase.com`** — older docs say `aws-0`. Both env URLs (master + agent) must match the host of the actual project. Construction-by-hand caused two outages in this session that cost ~30 min each.
- **Three Supabase URL types look alike:** dashboard (`supabase.com/dashboard/...`), API (`<ref>.supabase.co`), DB (`postgresql://<role>.<ref>:<pwd>@aws-X-...:6543/postgres`). Only the third is a Postgres connection. This was the source of the "wrong URL" error early in cloud apply.
- **Modal CLI rejects `list[str] | None` annotations.** Backfill takes `sources: str = ""` (comma-separated) instead.
- **Modal `run` doesn't echo function return values.** It logs the function lifecycle. To see results, query `compute_runs` afterwards or add a `local_entrypoint`.
- **Read-only override after free-tier breach is documented at supabase.com/docs/guides/platform/database-size#disabling-read-only-mode**. Three SQL commands in order: `set session characteristics as transaction read write;` → `vacuum;` → `set default_transaction_read_only = 'off';`. Banner UI can lag the actual permission state.
- **Supabase Pro upgrade does NOT auto-clear free-tier read-only carry-over.** You still need the override SQL. Disk size also doesn't auto-resize on upgrade — there's a "Manage disk" button that takes you through the resize, with a 4-hour cooldown between adjustments.

---

## Files written / modified this session

**New:**
- `apps/worker/common/{__init__.py, db.py, audit.py, lock.py, retry.py, sentry.py, CLAUDE.md}`
- `apps/worker/ingest/{__main__.py, models.py, _areas.py, fx.py, holidays.py, weather.py, jepx_prices.py, demand.py, generation_mix.py}`
- `apps/web/src/lib/supabase/{server.ts, client.ts}`
- `apps/web/src/components/dashboard/IngestStatusTable.tsx`
- `SESSION_LOG_2026-05-05.md` (this file)

**Modified:**
- `apps/worker/modal_app.py` (extended)
- `apps/worker/pyproject.toml` (added httpx, tenacity, pandas, sentry-sdk, pandas-stubs)
- `apps/worker/CLAUDE.md` (added Ingest discipline section + M3 milestone status)
- `apps/web/next.config.mjs` (repo-root .env.local + transpilePackages)
- `apps/web/package.json` (added @supabase/supabase-js, @supabase/ssr, dotenv)
- `apps/web/src/app/(app)/dashboard/page.tsx` (placeholder → ingest-status server component)
- `BUILD_SPEC.md` §2 (shadcn deferral note), §7.1 (generation_mix source line) + new §7.1.1 (per-utility table)

**Operator-side:**
- Supabase project upgraded free → Pro
- Disk resized to 8 GB
- Read-only override applied via SQL editor
- Modal Secret `jepx-supabase` created and refreshed (with `SENTRY_DSN`)
- Sentry project `jepx-storage` created, DSN added to `.env`

---

## Next steps

### Immediate (before M4 starts)
1. **Commit M3**. Suggested split:
   - `feat: M3 ingest infrastructure — common/ helpers + 6 source modules` (worker code)
   - `feat: M3 ingest dashboard + Modal cron` (web code + modal_app updates)
   - `docs: M3 spec updates + session log` (BUILD_SPEC §7.1.1 + this log + worker CLAUDE.md)
2. **Resolve the dashboard banner** — pause/resume the Supabase project to force a config reload, or open a support ticket. Functional impact is zero today, but visual is misleading.
3. **Optional — re-run weather backfill for KY only** if the Open-Meteo 429 left a noticeable gap. Single-source CLI: `python -m ingest weather --start 2020-01-01 --end 2026-04-30` (would re-fetch all 9, but idempotent).

### Milestone 4 — Stack model (next milestone, BUILD_SPEC §12)
Per spec:
- Generator master populated for ~100 thermal units across 9 areas (manual YAML curation; analyst-side work).
- `stack/build_curve.py` running daily, populating `stack_curves` and `stack_clearing_prices`.
- Backtest comparing modelled clearing price to realised JEPX price; **gate is RMSE < ¥3/kWh** on routine slots.
- Frontend `/dashboard` Section C (stack inspector) renders for the selected slot — first time we'll need shadcn primitives for real (Card, Tabs).
- Stop point: operator picks 5 slots across different areas/seasons, confirms modelled prices are within reasonable range.

Effort: 3-4 days per spec.

**M4 prerequisite that wasn't quite met in M3:** generation_mix data is TEPCO-only. Stack model uses `generation_mix_actuals.output_mw` for solar/wind capacity reduction in the merit-order curve. For non-TK areas, M4 will need either:
- A fallback that uses generator-level `generator_availability` data instead of area-aggregate mix, or
- A v2 expansion that implements the other 8 utility scrapers before M4 ships.

Worth raising with the operator at M4 kickoff.

### Open / parked items
- **shadcn/ui install** — re-evaluate at M4 dashboard buildout.
- **Generation_mix v2** — roll out the 8 non-TEPCO utility URLs in `_AREA_SOURCES`. Mechanical; each utility has the same area-supply-CSV pattern with minor URL/encoding/header variations.
- **Demand v2** — OCCTO direct migration per spec §7.1. The current v1 source (japanesepower.org) is permanently stuck at 2024-03-31.
- **`EXCHANGERATE_HOST_BASE_URL` in `.env`** — operator should rename to `FRANKFURTER_BASE_URL=https://api.frankfurter.dev`. Cosmetic; the worker reads `FRANKFURTER_BASE_URL` with a default, so the old key just sits unused.
- **Read-only banner** — currently still showing on dashboard despite functional writes. See "Decisions and gotchas" above.

---

## Where to resume

Open this log + `SESSION_LOG_2026-05-04.md` in a new conversation and ask Claude to "begin M4 planning, then implement". Memory at `~/.claude/projects/-Users-arkadyzelman-Desktop-Cursor-Projects-Project-Japan/memory/` holds the standing operator rules (no env reads, no unprompted commits) and project decisions (OpenAI for AI Analyst, frankfurter for FX).
