# apps/worker/agent — Claude Code context

AI Analyst — chat-style assistant with OpenAI function-calling. Reads
read-only data via `agent_readonly` Postgres role; writes audit + chat
state via service-role connection. Streams responses via SSE through a
FastAPI ASGI app deployed as `@modal.asgi_app(label="agent")`.

## Modules

| File | Purpose |
| --- | --- |
| `models.py` | Pydantic for ChatRequest, ToolCall, ToolResult, StreamEvent. |
| `safety.py` | sqlglot SELECT-only validator + token-budget helper. |
| `tools.py` | Seven §9.2 tools: query_data, describe_schema, create_chart, run_correlation, fit_quick_model, value_what_if, get_user_assets. |
| `prompts.py` | System prompt builder from `data_dictionary` table. |
| `loop.py` | OpenAI function-calling loop with streaming. |
| `service.py` | FastAPI ASGI app + `/chat` SSE endpoint. |

## Discipline

- **Three SQL safety layers must always be on.** sqlglot rejects non-SELECT/
  WITH; `agent_readonly` Postgres role physically cannot mutate; RLS scopes
  reads. No tool may bypass any of these.
- **Two Postgres connections per request.** `db.connect(env_var=
  "SUPABASE_AGENT_READONLY_DB_URL")` for `query_data` (reads); default
  service-role `db.connect()` for `chat_messages` / `agent_artifacts` /
  `compute_runs` writes. The service-role connection is NEVER exposed
  to the LLM context.
- **Wrap each tool call in `compute_run("agent_tool_call")`.** Inputs and
  outputs go to compute_runs.notes for audit. Truncate large outputs to
  ~10K chars before logging.
- **Token-budget check before every OpenAI call.** Sum tokens_in +
  tokens_out for the session; if cumulative ≥ 128,000 → return error
  event, do not call OpenAI.
- **OpenAI model**: `gpt-4o` by default; configurable via `OPENAI_MODEL`.
  128k context window matches the per-session token budget.
- **No model promotion.** `fit_quick_model` and `value_what_if` may run
  but MUST NOT INSERT/UPDATE the `models`, `valuations`, or `assets`
  tables. Audit-log only.
- **Plotly artifacts as raw JSON.** `create_chart` validates the
  Plotly figure spec shape (must have `data` and `layout`) and writes
  it verbatim to `agent_artifacts.spec_jsonb`. The frontend renders.
- **Streaming**: yield `StreamEvent` items as `data:` SSE lines via
  `sse-starlette`. Final event is `type='done'`.

## Don't

- Don't allow the LLM to see the service-role DB URL or service-role
  Supabase key. They're injected only via `common.db.connect()` and never
  surface in tool inputs/outputs.
- Don't add a tool that writes to user data. Adding such a tool requires
  a security review and a §9 spec amendment.
- Don't import from `vlstm/` or `lsm/` directly into `service.py` —
  agent reaches them via Modal HTTP endpoints (LSM specifically) so the
  agent container doesn't pull torch / numba into its image.
