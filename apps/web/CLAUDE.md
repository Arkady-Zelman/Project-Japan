# apps/web — Claude Code context

Next.js 14 (App Router, TypeScript strict + `noUncheckedIndexedAccess`, Tailwind v3). Deployed to Vercel `hnd1` (Tokyo).

See `BUILD_SPEC.md`:
- §6 — route surfaces (`/`, `/login`, `/dashboard`, `/workbench`, `/lab`, `/analyst`)
- §10 — realtime wiring (Supabase Realtime → frontend subscribes while Modal computes)
- §11 — Modal compute orchestration (Route Handlers under `src/app/api/` proxy to Modal HTTP endpoints)

## Conventions

- **Server Components by default.** Only mark a component `"use client"` when it actually uses state, effects, or browser APIs.
- **Mutations via Server Actions** unless the operation kicks off Modal compute, in which case use a Route Handler under `src/app/api/<job>/route.ts` that returns immediately and the frontend subscribes to a Supabase Realtime channel for the result.
- **Charts:** Recharts for standard dashboard charts; Plotly.js for the AI Analyst scratchpad (rendered from JSON spec the agent emits).
- **Client state:** Zustand. **Server cache:** TanStack Query v5.
- **Forms:** react-hook-form + zod. Validate every external input with zod before it crosses a process boundary.
- **Supabase clients:** `src/lib/supabase/client.ts` (browser, anon key) and `src/lib/supabase/server.ts` (server, service role). Never import the service-role client into a Client Component.

## Milestone status

- M1 (current): scaffold only. Landing + `/login` + `/dashboard` placeholders. No auth, no data, no shadcn primitives yet.
- M2: Supabase clients, generated DB types, login flow.
- M3: dashboard ingest-status page, real data fetching.
- shadcn/ui will be installed in M2 once we decide on Tailwind v3 vs v4 (shadcn's latest registry assumes v4).

## Don't

- Don't hardcode env vars — read from `process.env` only.
- Don't add a Vercel KV / Redis / Upstash dependency. Spec §2 explicitly excludes external caches.
- Don't add LangChain/LangGraph. The agent uses the OpenAI SDK directly from `apps/worker`.
