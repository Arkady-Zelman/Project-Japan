"""Postgres connection helpers — single source of truth for the pooler quirks.

Supabase's transaction pooler (port 6543) does NOT support PREPARE statements.
Every connection from this codebase MUST pass `prepare_threshold=None` or
psycopg's automatic prepare-after-N-uses behavior will eventually collide with
itself across pool checkouts and raise DuplicatePreparedStatement.

This is also where dotenv loading happens — call `connect()` and you get a
ready-to-use connection without each caller wiring the env-load themselves.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

# Resolve apps/worker/.env relative to this file so callers don't need to
# worry about the working directory. apps/worker/common/db.py → apps/worker/.env.
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _ensure_env_loaded() -> None:
    """Load apps/worker/.env into os.environ on first call. Idempotent."""
    if not os.environ.get("_JEPX_DOTENV_LOADED"):
        load_dotenv(_ENV_PATH)
        os.environ["_JEPX_DOTENV_LOADED"] = "1"


def get_url(env_var: str = "SUPABASE_DB_URL") -> str:
    """Return the connection URL from env, loading the dotenv file if needed.

    Raises RuntimeError if the var is unset — better than letting psycopg fail
    with a confusing parse error on an empty string.
    """
    _ensure_env_loaded()
    url = os.environ.get(env_var)
    if not url:
        raise RuntimeError(
            f"{env_var} not set in environment. Check apps/worker/.env."
        )
    return url


def connect(
    env_var: str = "SUPABASE_DB_URL",
    *,
    autocommit: bool = False,
    connect_timeout: int = 10,
) -> psycopg.Connection:
    """Open a Postgres connection compatible with the Supabase transaction pooler.

    Use as a context manager:

        with common.db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(...)

    Pass `env_var="SUPABASE_AGENT_READONLY_DB_URL"` for the agent's read-only role.
    """
    return psycopg.connect(
        get_url(env_var),
        autocommit=autocommit,
        connect_timeout=connect_timeout,
        prepare_threshold=None,  # Required for Supabase pooler — see module doc.
    )


def executemany_upsert(
    cur: psycopg.Cursor,
    sql: str,
    rows: Sequence[Sequence[Any]],
) -> int:
    """Execute an UPSERT for many rows, return rowcount.

    Thin wrapper for visibility — prefer this over raw `cur.executemany` so
    every UPSERT site is greppable. The caller writes the SQL with
    `INSERT ... ON CONFLICT ... DO UPDATE ...`.
    """
    cur.executemany(sql, rows)
    return cur.rowcount
