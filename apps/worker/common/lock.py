"""Postgres advisory locks — prevent concurrent ingest runs of the same source.

Per BUILD_SPEC §7.2, each ingest job acquires an advisory lock on its own name
so a slow daily run cannot overlap with a fast manual backfill. The transaction
scope (`pg_advisory_xact_lock`) means the lock is released automatically when
the connection's transaction ends — no explicit unlock needed even on crash.

Usage:

    with connect() as conn:
        with conn.cursor() as cur:
            advisory_lock(cur, "ingest_fx")
            ...
        conn.commit()  # releases the lock
"""

from __future__ import annotations

import psycopg


def advisory_lock(cur: psycopg.Cursor, name: str) -> None:
    """Acquire a transaction-scoped advisory lock keyed on `hashtext(name)`.

    Blocks until the lock is acquired. For non-blocking variants we'd use
    `pg_try_advisory_xact_lock` — not needed here because ingest jobs are
    short-running and serialization is acceptable.
    """
    cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (name,))
