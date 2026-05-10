"""SQL safety + token-budget helpers for the AI Analyst.

Three SQL safety layers per BUILD_SPEC §9.4. This module implements the
*first* (Python-side parser): `is_select_only(sql)` rejects every
non-SELECT/WITH statement before the SQL ever reaches the DB roundtrip.

The *second* layer is the `agent_readonly` Postgres role (defined in
`supabase/migrations/003_agent_readonly_role.sql`); it physically cannot
INSERT/UPDATE/DELETE on user-scoped tables regardless of what SQL the
agent constructs. The *third* layer is RLS: reference + market + model
tables are SELECT-only for the role, user-scoped tables return zero rows.

Token-budget helper: `get_session_token_total(cur, session_id)` sums
`tokens_in + tokens_out` from `chat_messages` for the session. The
service rejects new prompts when the running total exceeds the
SESSION_TOKEN_LIMIT (128k tokens, matching gpt-4o's context).
"""

from __future__ import annotations

import logging
from uuid import UUID

import psycopg
import sqlglot
import sqlglot.errors
import sqlglot.expressions as exp

logger = logging.getLogger("agent.safety")

# Per BUILD_SPEC §9.4: 128k tokens of total OpenAI context per session.
SESSION_TOKEN_LIMIT = 128_000


def is_select_only(sql: str) -> tuple[bool, str | None]:
    """Validate that `sql` is a SELECT or WITH-SELECT statement only.

    Returns (ok, reason). On rejection, `reason` is a short error message
    that's safe to surface back to the LLM/user (it does not echo the
    rejected SQL itself).

    Rejects:
      - INSERT, UPDATE, DELETE, MERGE, TRUNCATE
      - DDL: CREATE, ALTER, DROP, COMMENT
      - Privilege ops: GRANT, REVOKE
      - Multi-statement strings (we accept only a single statement)
      - Unparseable SQL
      - SET / SET ROLE / SET LOCAL (could be used to escalate)
      - COPY (file I/O), CALL (procedural), EXECUTE
    """
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as e:
        return False, f"sql parse error: {str(e)[:200]}"
    statements = [s for s in statements if s is not None]
    if not statements:
        return False, "empty SQL"
    if len(statements) > 1:
        return False, "multi-statement SQL not allowed; submit one statement at a time"

    root = statements[0]
    if not isinstance(root, (exp.Select, exp.Subquery, exp.Union, exp.Intersect, exp.Except)):
        # Allow CTE-style WITH ... SELECT
        if not isinstance(root, exp.With):
            kind = type(root).__name__
            return False, f"only SELECT / WITH-SELECT allowed; got {kind}"

    # Walk the entire tree and reject if it contains any explicitly mutating
    # node anywhere (defensive against subselects with side effects).
    forbidden = (
        exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop,
        exp.Create, exp.Alter, exp.Comment,
        exp.TruncateTable,
        exp.Command,        # set, execute, call, copy etc.
    )
    for node in root.walk():
        if isinstance(node, forbidden):
            return False, f"forbidden node in SQL: {type(node).__name__}"
    return True, None


def get_session_token_total(cur: psycopg.Cursor, session_id: UUID | str) -> int:
    """SUM(coalesce(tokens_in, 0) + coalesce(tokens_out, 0)) for the session."""
    cur.execute(
        """
        select coalesce(sum(coalesce(tokens_in, 0) + coalesce(tokens_out, 0)), 0)
        from chat_messages where session_id = %s
        """,
        (str(session_id),),
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


def remaining_token_budget(cur: psycopg.Cursor, session_id: UUID | str) -> int:
    """Tokens remaining in the session's 128k budget. Negative iff over."""
    return SESSION_TOKEN_LIMIT - get_session_token_total(cur, session_id)
