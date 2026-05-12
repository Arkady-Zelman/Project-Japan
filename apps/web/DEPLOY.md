# Deploying `apps/web` to Vercel

## TL;DR — what actually moves to Vercel

**Nothing data-related.** The app on your laptop has always been a thin Next.js client talking to two cloud backends:

| Layer | Where it lives | When you deploy |
|---|---|---|
| **Postgres + Realtime** | Supabase `ap-northeast-1` | unchanged — Vercel just connects to the same project |
| **Python ML / cron / ingest** | Modal Tokyo | unchanged — Vercel Route Handlers call the same HTTPS endpoints |
| **Next.js UI** | `npm run dev` on your laptop | now also served from `https://<project>.vercel.app` |

So "porting to Vercel" is really: deploy the Next.js bundle to Vercel's CDN, point it at the same Supabase + Modal you've been using all along, paste env values into Vercel's env UI. There is **no data to upload from your PC** — Supabase is the database, your laptop never was.

The 30-min map refresh, the Realtime ingest updates, the VLSTM forecasts, the BoS strategy — all already round-trip through cloud services. They'll behave identically from a Vercel URL.

---

## Prerequisites (one-time)

1. **Vercel account** with access to a team (Hobby works for testing; Pro for the `hnd1` region guarantee).
2. **CLI upgrade.** Yours is 51.x; latest is 53.x.
   ```bash
   npm i -g vercel@latest
   vercel --version   # should print 53.x
   ```
3. **GitHub remote** for this repo (optional but recommended — preview deploys per branch require it).
4. The 16 env values you currently have in `.env.local` and `apps/worker/.env`. Do **not** commit either file; Vercel doesn't read them.

---

## One-time project setup

From inside `apps/web`:

```bash
cd "apps/web"
vercel link
```

- Pick or create a Vercel project (e.g. `jepx-storage`).
- When asked for the **root directory**, accept the current dir (`apps/web`). Vercel auto-detects Next.js.
- The `vercel.json` in this folder pins `regions: ["hnd1"]` and `framework: nextjs`. You can additionally confirm the region in Project Settings → Functions on the dashboard.

### Update Supabase auth allow-list

In Supabase dashboard → **Authentication → URL Configuration**, add:

- **Site URL:** `https://<your-prod-domain>` (or the `*.vercel.app` URL after first deploy)
- **Redirect URLs (allow-list):**
  - `https://<your-prod-domain>/auth/callback`
  - `https://*.vercel.app/auth/callback` ← matches every preview deploy

Without this, magic-link logins from the deployed site bounce.

---

## Setting env vars on Vercel

Vercel has a first-class env system; **you do not upload `.env.local`**. Three scopes exist — Production, Preview, Development — and each variable is set per-scope.

Two ways to add them:

- **Dashboard:** Project → Settings → Environment Variables → "Add New". Paste value, tick the scopes that apply. Use the **Sensitive** toggle for service-role keys.
- **CLI:** from `apps/web`, run the commands below. Each prompts for the value on stdin (so it doesn't hit shell history).

### Production scope (15 keys)

```bash
# Supabase
vercel env add NEXT_PUBLIC_SUPABASE_URL production
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production
vercel env add SUPABASE_SERVICE_ROLE_KEY production   # mark Sensitive in dashboard after

# Modal endpoints (from `modal deploy modal_app.py` output)
vercel env add MODAL_LSM_ENDPOINT production
vercel env add MODAL_BACKTEST_ENDPOINT production
vercel env add MODAL_AGENT_ENDPOINT production

# Sentry — auth token enables source-map upload at build
vercel env add NEXT_PUBLIC_SENTRY_DSN production
vercel env add SENTRY_DSN production
vercel env add SENTRY_AUTH_TOKEN production            # mark Sensitive
vercel env add SENTRY_ORG production
vercel env add SENTRY_PROJECT production

# PostHog
vercel env add NEXT_PUBLIC_POSTHOG_KEY production
vercel env add NEXT_PUBLIC_POSTHOG_HOST production
```

Repeat the same keys for **preview** if you want preview deploys to talk to prod Supabase (recommended for a single-developer project):

```bash
vercel env pull --environment=production .env.production.tmp   # snapshot
# Then in the dashboard: bulk-copy each var to the Preview scope.
```

### Development scope only — dev-session bypass

```bash
vercel env add JEPX_DEV_USER_ID development
```

**Do not set `JEPX_DEV_USER_ID` in Production or Preview.** It bypasses Supabase auth using a fixed UUID; in prod it would let anyone act as that user. It only exists for `vercel dev` parity with `npm run dev`.

---

## Deploy

From `apps/web`:

```bash
# First-ever deploy: pushes a preview build to a unique URL
vercel

# Promote to production (or push to your main branch if Git integration is on)
vercel --prod
```

The first build typically takes ~3–5 minutes (Next.js compile + Sentry source-map upload). Subsequent builds with the same dependencies are faster.

After it lands, click around:

- `/` → redirects to `/dashboard`
- `/dashboard` → Map tab loads, 9 regions render, hero metrics populate within ~2s
- Switch to Forecast / Stack / Regime / Strategy tabs → each lazy-loads and pulls live data
- `/workbench` and `/lab` → require login; magic-link should arrive in inbox and resolve back to the deployed origin (only works once the Supabase redirect allow-list is updated)

---

## Local ↔ Vercel parity workflow

This is the loop that keeps "what I see on my Mac" and "what the world sees on Vercel" identical:

### 1. Day-to-day: develop locally, deploy on git push

```bash
# Local
cd "apps/web"
npm run dev           # localhost:3000, reads ../../.env.local

# When you're happy with changes
git add -A
git commit -m "..."
git push              # Vercel auto-deploys to a preview URL
                       # Promote with `vercel --prod` or via dashboard
```

Both environments read from the same Supabase + Modal, so behaviour is identical except for the URL.

### 2. After rotating an env var

If you change a Supabase key, Modal URL, etc.:

```bash
# 1. Update locally
vim ../../.env.local       # (don't commit this file)

# 2. Mirror to Vercel
vercel env rm KEY production
vercel env add KEY production

# 3. Trigger redeploy (env changes don't auto-rebuild)
vercel --prod --force
```

### 3. Pulling Vercel's env into local for `vercel dev`

If you want to run the app locally against the **production** env (e.g. to repro a deploy-only bug):

```bash
cd "apps/web"
vercel env pull .env.production.local    # writes the production scope into this file
vercel dev                                 # runs Next.js with that env, mimicking Vercel runtime
```

`.env.production.local` is gitignored by Next.js convention. Delete it when you're done; or re-pull whenever you need fresh values.

### 4. Bringing data into a new Supabase project

You almost certainly **don't** need to do this — keep using the existing Supabase project for both local and Vercel. But if you ever do (e.g. spin up a staging DB):

- The schema lives in `supabase/migrations/001_init.sql` through `005_latest_coverage_slot.sql`. Re-running those gets you an empty DB with the right shape.
- The data is regenerated by Modal cron jobs (`ingest_daily`, `forecast_vlstm_*`, etc.). One day of ingest gets the dashboard non-empty.
- Backfill commands live in `apps/worker/ingest/_area_supply.py` and friends.

---

## How env vars actually reach the running app

| Layer | How it gets the value |
|---|---|
| **Local `npm run dev`** | `next.config.mjs` loads `../../.env.local` via `dotenv` before Next.js boots |
| **Vercel build (`next build`)** | Vercel platform injects all Production-scoped vars into `process.env` before the build container starts |
| **Vercel runtime (Route Handlers, Server Components)** | Same `process.env` available at request time |
| **Client bundle** | Only `NEXT_PUBLIC_*` vars are inlined at build time. Service-role keys never reach the browser. |

The `dotenv` call in `next.config.mjs` silently no-ops on Vercel because the `.env.local` path doesn't exist there. No conflict.

---

## Post-deploy verification checklist

After `vercel --prod`:

1. Production URL loads with no console errors (`F12` → Console).
2. `/dashboard` Map tab shows live regional data within 3s.
3. Region click expands accordion with donut + breakdown.
4. **Strategy** tab loads, BoS schedule renders, P&L curve draws.
5. `/login` → magic-link arrives, redirects to deployed origin (not localhost), session persists across page reload.
6. `/workbench` → create an asset, hit Run valuation. Modal endpoint responds within ~30s; results stream via Realtime.
7. `/lab` → queue a backtest, comparison table updates.
8. Sentry dashboard shows the deploy as a new release; trigger a deliberate error (e.g. visit `/api/foo-404`) and confirm it appears within 60s.
9. PostHog dashboard records page views with the correct project key.
10. Wait ~31 minutes → the map's last-updated timestamp advances without a page reload (Realtime + interval heartbeat).

---

## Out of scope here

- **Custom domain.** Add via Project Settings → Domains; Vercel handles cert.
- **Modal redeploy.** Independent of Vercel. Run `npm run worker:modal -- deploy modal_app.py` when worker code changes.
- **Database migrations.** Apply via `supabase db push` or the Supabase dashboard. Not part of `vercel --prod`.
- **Vercel Cron.** Do not add. Cron lives on Modal per `BUILD_SPEC.md` §"Stack constraints".
- **`@vercel/config` / `vercel.ts`.** Current `vercel.json` is sufficient; upgrade to TS config only if you start needing dynamic build logic.
