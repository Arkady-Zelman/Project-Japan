# JEPX-Storage

Power-market analytics platform for the Japan Electric Power Exchange. Stack model + VLSTM forecaster + LSM storage valuer + AI Analyst, on a single Postgres DB.

See `BUILD_SPEC.md` for the full specification — it is the source of truth for schema, algorithms, units, and milestones. Do not deviate without amending the spec.

## Layout

```
apps/web/             Next.js 14 (App Router, Tailwind) — Vercel hnd1
apps/worker/          Python + Modal (Tokyo) — ingest, ML, LSM, AI agent
packages/shared-types/  Generated Postgres types shared TS ↔ Python
supabase/migrations/  SQL migrations (001 schema, 002 RLS+Realtime, 003 agent role)
```

## Quickstart

Prereqs: Node 20+, Python 3.11, [Modal CLI](https://modal.com/docs/guide) authenticated, Docker (for local Supabase), and the Supabase CLI (`brew install supabase/tap/supabase`).

```bash
# 1. Install JS deps
npm install

# 2. Copy env templates and fill in (Supabase, OpenAI, Modal, etc.)
cp .env.local.example .env.local
cp .env.example apps/worker/.env

# 3. Install worker deps into a Python 3.11 venv
cd apps/worker
python3.11 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
cd ../..
```

### Frontend / Modal worker

```bash
npm run dev                          # Next.js at http://localhost:3000
npm run worker:modal -- deploy modal_app.py    # deploy worker stub to Modal Tokyo
```

### Database — local development

The Supabase CLI boots a full local stack (Postgres, Auth, Realtime, Storage) inside Docker.

```bash
supabase start                       # first time pulls images; subsequent boots ~10s
supabase db reset                    # runs supabase/migrations/*.sql in order
```

Verify a few things in the local stack:

```bash
psql 'postgresql://postgres:postgres@localhost:54322/postgres' -c '\dt public.*'
psql 'postgresql://postgres:postgres@localhost:54322/postgres' \
  -c "select tablename from pg_publication_tables where pubname='supabase_realtime';"
```

### Database — applying to the cloud project

After setting `apps/worker/.env::SUPABASE_DB_URL` to your project's pooled connection string:

```bash
supabase link --project-ref <your-project-ref>
supabase db push                     # applies pending migrations to the linked project
```

Or paste each migration file into the Supabase SQL editor in order: `001_init.sql` → `002_rls.sql` → `003_agent_readonly_role.sql`.

### Reference data + data dictionary seed

```bash
cd apps/worker
./.venv/bin/python -m seed.load_reference         # 10 areas, 12 fuels, 8 unit types, ~200 holidays
./.venv/bin/python -m seed.load_data_dictionary   # 226 column descriptions for the AI agent
```

Both scripts read `apps/worker/.env::SUPABASE_DB_URL` and are idempotent.

### Generated TypeScript types

After migrations are applied to the cloud project, regenerate the shared types:

```bash
supabase gen types typescript --project-id <ref> > packages/shared-types/src/index.ts
```

Re-run any time the schema changes.

## Operator manual steps after `003_agent_readonly_role.sql`

1. **Set `agent_user` password** in Supabase Dashboard → Database → Roles, then copy the resulting connection string into `apps/worker/.env::SUPABASE_AGENT_READONLY_DB_URL`.
2. **Realtime** is wired automatically by `002_rls.sql` (publication append). No dashboard clicks needed.
3. **Type generation** (above) once the schema is applied.

## Milestone status

Currently at **Milestone 2 — Database**. See `BUILD_SPEC.md` §12 for the full sequence.
