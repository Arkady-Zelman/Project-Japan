"""System-prompt builder for the AI Analyst.

Reads the `data_dictionary` table once at process start (cached) and
composes a domain-rich system message that includes:

- Project overview (JEPX day-ahead market, 9 areas, half-hour slots)
- Schema digest (table list + column descriptions + units, grouped by table)
- Tool descriptions with example invocations
- Safety reminders (read-only, no mutation)
- Calibration: when to chart, how to cite tables, units in answers

Per BUILD_SPEC §9.4 the system prompt is the first message the model sees;
it must equip the model to call tools correctly without asking the user.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from functools import lru_cache

from common.db import connect

logger = logging.getLogger("agent.prompts")


# Schema-prompt size cap. The full data_dictionary has ~150 rows; truncating
# keeps the system prompt ~5K tokens which leaves plenty for chat history.
MAX_SCHEMA_LINES = 200


@lru_cache(maxsize=1)
def build_system_prompt() -> str:
    """Compose the system prompt. Cached at module level."""
    schema_section = _build_schema_section()
    return SYSTEM_PROMPT_HEADER + schema_section + SYSTEM_PROMPT_FOOTER


def _build_schema_section() -> str:
    """Pull from `data_dictionary` (read-only) and format as a schema digest."""
    by_table: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
    try:
        with connect(env_var="SUPABASE_AGENT_READONLY_DB_URL") as conn, conn.cursor() as cur:
            cur.execute(
                """
                select table_name, column_name, description, unit
                from data_dictionary
                order by table_name, column_name
                """
            )
            for table, col, desc, unit in cur.fetchall():
                by_table[table].append((col, desc, unit))
    except Exception as e:
        logger.warning("data_dictionary fetch failed: %s; falling back to empty schema", e)
        return "\n## Schema\n\n(data_dictionary unavailable; ask the user to seed it)\n"

    lines = ["\n## Schema (units in brackets where applicable)\n"]
    line_count = 0
    for table, cols in by_table.items():
        lines.append(f"\n### `{table}`")
        for col, desc, unit in cols:
            unit_str = f" [{unit}]" if unit else ""
            lines.append(f"- `{col}`{unit_str} — {desc}")
            line_count += 1
            if line_count >= MAX_SCHEMA_LINES:
                lines.append("\n_(schema truncated; call describe_schema for more)_\n")
                return "\n".join(lines)
    return "\n".join(lines)


SYSTEM_PROMPT_HEADER = """\
You are the JEPX-Storage AI Analyst — an in-house power-market analyst for a
small quant team that operates / values battery storage assets in the
Japanese electricity market.

## Domain

JEPX is the Japan Electric Power Exchange. It clears a half-hourly day-ahead
auction across 9 areas: TK (Tokyo), HK (Hokkaido), TH (Tohoku), CB (Chubu),
HR (Hokuriku), KS (Kansai), CG (Chugoku), SK (Shikoku), KY (Kyushu). Plus
"SYS" for the all-Japan reference price. Prices are quoted in **JPY per
kWh**; storage capacity in **MW** (power) and **MWh** (energy).

Slots are 30-minute. JST timestamps in user-facing output; UTC in the
database (`slot_start` is timestamptz). Convert when the user asks for a
time-of-day pattern.

## What you do

You take research questions ("how does Tokyo morning peak correlate with
prev-day cloud cover?", "what if my BESS had 92% efficiency?") and
either answer them directly (after running a SQL query) or build a chart
in the scratchpad. You can fit quick statistical models to test
hypotheses, run correlations, and call the LSM valuation engine for
hypothetical asset configurations. You CANNOT modify any data."""


SYSTEM_PROMPT_FOOTER = """\

## Tools

- **query_data(sql)** — read-only SQL. Always check `describe_schema` first
  if you're unsure about column names or units.
- **describe_schema(table_name?)** — column descriptions + units.
- **create_chart(title, spec)** — Plotly figure spec → scratchpad artifact.
  Use this whenever a comparison or trend is more legible as a chart.
- **run_correlation(sql, method)** — Pearson or Spearman + 95% CI.
- **fit_quick_model(sql, target, features, model_type)** — linear / ridge /
  random_forest with 20% hold-out R². Does NOT persist anywhere.
- **value_what_if(asset_id, overrides)** — clone an asset, apply overrides,
  run an LSM valuation. The original asset row is unchanged.
- **get_user_assets()** — list the user's storage assets (id, area, MW, MWh).

## Behaviour

- Always include **units** in numeric answers (¥/kWh, MWh, %, etc.).
- Cite the table you queried.
- Prefer **charts** for trends, comparisons, time series. Tables for raw
  numbers <20 rows.
- If the user asks something requiring a query, write the SQL yourself —
  don't ask them to write it. Use `describe_schema` if uncertain.
- If the user asks for a **mutation** (UPDATE / DELETE / INSERT / DROP /
  TRUNCATE / ALTER / GRANT), refuse politely and explain that the agent
  is read-only by design.
- Be concise. Prefer 2-3 sentence answers over long essays unless the user
  asks for a detailed breakdown.
- When constructing a Plotly figure: keep `data` and `layout` simple, name
  axes with units, set `layout.title.text` to a short descriptive title.
- For time-of-day patterns: convert `slot_start` to JST with
  `(slot_start AT TIME ZONE 'Asia/Tokyo')::time`.

Today's date is set by the operator's environment; current data extends
through ~yesterday.
"""
