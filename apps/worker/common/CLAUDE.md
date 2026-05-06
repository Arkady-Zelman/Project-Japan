# apps/worker/common — Claude Code context

Shared infrastructure used by every Postgres-touching job in the worker. Five small modules, each with one job.

## Modules

| File | Purpose |
| --- | --- |
| `db.py` | `connect()` returns a `psycopg.Connection` pre-configured for Supabase's transaction pooler (`prepare_threshold=None`). Loads `apps/worker/.env` once on first call. |
| `audit.py` | `with compute_run("ingest_fx")` context manager. Inserts a `compute_runs` row at start, updates it on exit with `status`, `duration_ms`, `error`, `output` JSON. |
| `lock.py` | `advisory_lock(cur, "ingest_fx")` — Postgres `pg_advisory_xact_lock`, scoped to the transaction so the lock auto-releases. |
| `retry.py` | `@retry_transient` decorator using tenacity. 5 attempts, exponential backoff with jitter. Retries on transient HTTP / DB errors only. |
| `sentry.py` | `init_sentry()` (no-op if `SENTRY_DSN` unset), `tag_source("fx")`. Scheduled Modal functions call `init_sentry()` once at entry. |

## Discipline

- **Every ingest, stack, regime, lsm, valuation, agent-tool function MUST connect via `common.db.connect()`** — it's the single place we set `prepare_threshold=None`. Direct `psycopg.connect()` calls bypass that and will eventually break on the pooler.
- **Every long-running compute MUST be wrapped in `compute_run(kind)`.** The dashboard reads `compute_runs` to show health; missing rows = blind operator.
- **Every ingest job MUST acquire its own advisory lock** (`advisory_lock(cur, "ingest_<source>")`) — concurrent runs of the same source corrupt audit accounting and can race on UPSERTs.
- **Wrap upstream HTTP fetches with `@retry_transient`** — not the entire ingest function (we don't want to re-write rows on retry), just the network call.

## Don't

- Don't add I/O at module import time. `init_sentry()` is opt-in; `connect()` only opens when called.
- Don't add convenience helpers that hide which env var is used. Every connection's URL source is greppable.
- Don't add a connection pool here — psycopg's pooler-mode connection is one-shot per `with connect():` block. Modal cold-starts handle "pooling" at the function level.
