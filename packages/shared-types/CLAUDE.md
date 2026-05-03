# packages/shared-types — Claude Code context

Generated TypeScript types from the Supabase Postgres schema, consumed by `apps/web` (and mirrored manually to Pydantic models in `apps/worker` where useful).

## Milestone status

M1 (current): empty `src/index.ts` placeholder.

M2: regenerate via `supabase gen types typescript --project-id <id> > packages/shared-types/src/index.ts` after `001_init.sql` is applied. Re-run whenever the schema changes — these types are how `apps/web` stays in sync with the DB.

## Don't

- Don't hand-edit `src/index.ts`. It is regenerated output.
- Don't import from this package inside `apps/worker` Python — Pydantic models are defined separately on the worker side.
