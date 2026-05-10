# Session log — 2026-05-10 (M9)

Continuation of M8 (committed `a2262a0` with the strategy backtest engine deployed and `/lab` rendering all four strategies' equity curves live). Started at the M8 STOP gate (working tree clean), planned M9 AI Analyst, then implemented end-to-end.

---

## What shipped (M9)

### Plan + ground rules
- Three clarifying questions answered:
  - Tool scope: **all 7 tools per §9.2** — `query_data`, `describe_schema`, `create_chart`, `run_correlation`, `fit_quick_model`, `value_what_if`, `get_user_assets`
  - Auth: **hardcoded dev user** consistent with M7/M8; multi-user Supabase login deferred to M9.5
  - Streaming: **SSE token-by-token** via `sse-starlette` on Modal + Vercel `/api/agent` relay

### Phase 0 — Deps + image (~20 min)
- `pyproject.toml` + `modal_app.py::base_image`: added `openai>=1.50`, `sqlglot>=23`, `scikit-learn>=1.5`, `sse-starlette>=2.1`. (FastAPI was already present from M7.)
- Web `package.json`: added `plotly.js-basic-dist@^2.35`, `react-plotly.js@^2.6`, `@types/react-plotly.js@^2`.
- `agent` registered in `add_local_python_source(...)`.

### Phase 1 — Tools + safety (~3 hrs)
- `agent/safety.py::is_select_only` validates SQL via `sqlglot.parse(read="postgres")`. Rejects multi-statement strings, every mutation node (Insert/Update/Delete/Merge/Drop/Create/Alter/Comment/TruncateTable/Command). 13/13 unit tests pass.
- `agent/safety.py::get_session_token_total` sums `tokens_in + tokens_out` from `chat_messages` for a given session — used by the loop's pre-flight 128k budget gate.
- `agent/tools.py` — seven tool implementations:
  - **query_data**: opens `agent_readonly` connection, sets `statement_timeout='30s'`, returns rows + columns. Caps at 1,000 rows.
  - **describe_schema**: pulls from `data_dictionary` (already populated by M2 `seed.load_data_dictionary`).
  - **create_chart**: validates Plotly figure shape (`{data, layout}`), inserts `agent_artifacts` row.
  - **run_correlation**: pearson / spearman + Fisher z 95% CI on a 2-column SELECT.
  - **fit_quick_model**: linear / ridge / random_forest with 80/20 split + R² on hold-out. Persists nothing (per §9.4 "no model promotion").
  - **value_what_if**: clones the asset row with overrides applied, queues a valuation, fires Modal LSM endpoint, polls until done, deletes the clone. Original asset row never touched.
  - **get_user_assets**: SELECT from `assets` filtered by `user_id` and `metadata->>'what_if' != 'true'`.
- All tools wrapped in `compute_run("agent_tool_call")` for audit.
- Adversarial `UPDATE jepx_spot_prices SET price_jpy_kwh = 0` rejected by `is_select_only` with explicit reason; verified `agent_readonly` role independently rejects with `InsufficientPrivilege: permission denied for table chat_sessions`.

### Phase 2 — Loop + service (~3 hrs)
- `agent/prompts.py::build_system_prompt` — composes a ~4,500-token system message from `data_dictionary`. Cached via `@lru_cache`. Includes domain context, schema digest grouped by table, tool docs, safety reminders, calibration ("always include units, prefer charts for trends").
- `agent/loop.py::run_agent_loop` — async generator yielding `StreamEvent` items per BUILD_SPEC §9. Handles:
  - Token-budget gate (rejects if cumulative ≥ 128k).
  - OpenAI streaming with `tools=...` and `stream_options={"include_usage": True}`.
  - Tool-call accumulation per `delta.index`.
  - Parallel tool execution via `loop.run_in_executor(_threadpool, fn, args, ctx)`.
  - Persistence of one assistant `chat_messages` row per loop iteration (with the in-progress tool_calls jsonb) plus one tool `chat_messages` row per round.
  - 8-iteration loop cap.
- `agent/service.py::build_app()` — FastAPI ASGI app. `GET /health` + `POST /chat` (SSE via `sse-starlette`). Reads `X-User-Id` header (the Vercel relay attaches `JEPX_DEV_USER_ID`). Resolves session_id (validates ownership, creates new if missing) before kicking the loop.

### Phase 3 — Modal ASGI deploy (~30 min)
- `modal_app.py::agent_app()` decorated with `@modal.asgi_app(label="agent")`, cpu=2.0, timeout=300s, max_containers=10.
- Deploy succeeded at `https://projectjapan--agent.modal.run` (15 functions deployed; one new web function alongside the existing `lsm-value` and `run-backtest`).
- `MODAL_AGENT_ENDPOINT` written to `.env.local`.

### Phase 4 — Web relay route + chat session hook (~2 hrs)
- `apps/web/src/app/api/agent/route.ts` — POST handler. zod-validates body, attaches `X-User-Id: ${JEPX_DEV_USER_ID}`, fetches Modal `/chat`, pipes the SSE response body straight back to the browser via the Web Streams API.
- `apps/web/src/hooks/useChatSession.ts` — subscribes to `chat_messages` and `agent_artifacts` postgres-changes channels filtered by session_id. `send(text)` opens the SSE stream, accumulates `token` events into `inFlightAssistantText`, and accumulates `tool_call` events into `inFlightToolCalls`. When a `done` event arrives the realtime subscription has already delivered canonical state, so the in-flight buffer flushes.

### Phase 5 — Chat + scratchpad UI (~3 hrs)
- `apps/web/src/components/analyst/AnalystClient.tsx` — 3-column grid: sessions sidebar, chat interface, scratchpad pane.
- `ChatInterface.tsx` — message thread with user/assistant/tool bubbles. Tool messages collapse into a `<details>` block. In-flight assistant bubble shows incoming tokens + the names of tools being called.
- `ScratchpadPane.tsx` — renders `agent_artifacts` filtered by type tabs (charts / queries / models). Charts use `<PlotlyArtifact>` which dynamic-imports `plotly.js-basic-dist` and `react-plotly.js/factory` (lazy-loaded so first paint isn't delayed).
- `apps/web/src/app/(app)/analyst/page.tsx` — Server Component fetches the dev user's chat sessions and passes them to `AnalystClient`.
- TypeScript clean; `/analyst` returns 200 on the dev server.

### Phase 6 — Spec amendments + session log + commits (this section)
- BUILD_SPEC §12 M9 — flagged the gate result + the OpenAI-quota blocker.
- `apps/worker/CLAUDE.md` — milestone status entry.

---

## STOP-gate state

### Structural verification

| Gate | Status |
|---|---|
| Deps install (`openai`, `sqlglot`, `sklearn`, `sse_starlette`) | ✅ |
| `agent_readonly` connection works (SELECT 1) | ✅ |
| sqlglot rejects 10/10 mutation patterns; accepts SELECT/WITH | ✅ |
| Adversarial DB-side test: INSERT on `agent_readonly` raises InsufficientPrivilege | ✅ |
| Modal ASGI deploys; `GET /health` returns 200 | ✅ |
| End-to-end SSE stream events flow back through `/api/agent` | ✅ (session, error, done events observed) |
| `/analyst` UI renders | ✅ |
| 7 §13 smoke-test scenarios pass | ⚠ pending OpenAI quota |

### OpenAI quota blocker

First end-to-end POST to `/chat` returned:

```
event: error
data: {"message": "OpenAI error: Error code: 429 - {'error': {'message':
'You exceeded your current quota, please check your plan and billing details.',
'type': 'insufficient_quota', 'param': None, 'code': 'insufficient_quota'}}"}
```

The agent pipeline is fully wired — sqlglot parser, agent_readonly role, FastAPI/SSE, Modal ASGI, Vercel relay, browser SSE consumption, Realtime subscriptions, Plotly artifact rendering — but each turn calls OpenAI's chat-completions endpoint, and the operator's account is out of credits. Once topped up the seven §13 scenarios should run; until then the M9 STOP gate is **structurally green, functionally pending**.

---

## Decisions and gotchas worth re-reading

- **`@modal.asgi_app(label="agent")` ≠ `@modal.fastapi_endpoint`.** ASGI wraps a whole FastAPI app and supports SSE properly via `sse-starlette`. fastapi_endpoint is per-route and doesn't support streaming. M7/M8 used fastapi_endpoint; M9 needed ASGI.
- **`@lru_cache` on the system-prompt builder** — saves ~50ms per request after the first cold-start. Module-level cache invalidates on container restart, which is the right cadence for the data_dictionary (operator runs `seed.load_data_dictionary` rarely).
- **Tool concurrency** — OpenAI emits `tool_calls` in a single assistant message; we run them in parallel via `asyncio.gather` over `run_in_executor`. The threadpool has 4 workers — plenty for the typical 1-3 tools per turn.
- **Service-role connection never exposed to LLM** — `connect()` (defaults to `SUPABASE_DB_URL`) is used only for chat_messages / agent_artifacts / clone-asset writes. The `query_data` tool opens its own `agent_readonly` connection per call. The LLM never sees credentials or any DB URL.
- **value_what_if cleanup** — clone asset + valuation rows are deleted in the `finally` block via service-role connection (which has DELETE privileges; agent_readonly does not). Failure to clean up only leaves a `[what-if]`-prefixed asset row in the DB, which `get_user_assets` filters out.
- **Plotly bundle size** — `plotly.js-basic-dist` (~700 KB) is dynamic-imported via `next/dynamic` so the analyst page TTFB doesn't pay for it. The full `plotly.js` would have been ~3.5 MB.
- **OpenAI streaming delta accumulation** — function-call arguments arrive as fragmented strings across many delta chunks. The `tool_calls_acc[idx]` dict accumulates `function.arguments` as a string, then we `json.loads` it once per call.
- **Token-budget gate is pre-flight only** — we check at the start of each `run_agent_loop` invocation (= one user turn), not before each in-loop OpenAI call. A single turn that consumes >128k tokens would still complete but the next turn would be rejected. Acceptable for v1.

---

## Files written / modified this M9 phase

**New (worker):**
- `apps/worker/agent/__init__.py`
- `apps/worker/agent/CLAUDE.md`
- `apps/worker/agent/models.py` — Pydantic schemas
- `apps/worker/agent/safety.py` — sqlglot SELECT-only + token budget
- `apps/worker/agent/tools.py` — 7 tools + OpenAI tool schemas
- `apps/worker/agent/prompts.py` — system prompt builder
- `apps/worker/agent/loop.py` — OpenAI streaming function-calling loop
- `apps/worker/agent/service.py` — FastAPI ASGI app

**New (web):**
- `apps/web/src/app/(app)/analyst/page.tsx`
- `apps/web/src/app/api/agent/route.ts`
- `apps/web/src/components/analyst/AnalystClient.tsx`
- `apps/web/src/components/analyst/ChatInterface.tsx`
- `apps/web/src/components/analyst/ScratchpadPane.tsx`
- `apps/web/src/components/analyst/PlotlyArtifact.tsx`
- `apps/web/src/hooks/useChatSession.ts`

**Modified:**
- `apps/worker/pyproject.toml` — `openai`, `sqlglot`, `scikit-learn`, `sse-starlette` added to base deps
- `apps/worker/modal_app.py` — `agent_app` ASGI function; `agent` in `add_local_python_source`
- `apps/worker/CLAUDE.md` — M9 milestone status entry
- `apps/web/package.json` — Plotly deps
- `BUILD_SPEC.md` §12 M9 — gate result + OpenAI quota note
- `SESSION_LOG_2026-05-10-M9.md` (this file)
- `.env.local` — `MODAL_AGENT_ENDPOINT` appended

## Out of scope (parked as M9.5)

- **Multi-user Supabase login** — hardcoded dev user only. M9.5 wires real JWT relay through `X-User-Id` (or replaces it with a verified JWT header).
- **Agent artifact expiry cron** — spec §9.4 says "rows older than 7 days deleted nightly". Manual-only for now (Modal free-tier 5-cron cap).
- **Token-budget mid-loop check** — currently pre-flight only.
- **describe_schema rich tree response** — currently flat rows.
- **Streaming improvements** — tool-result events arrive only after the tool completes; partial tool-result streaming would be useful for slow tools but adds structural complexity.
- **§13 smoke-test execution** — blocked on OpenAI credits.
