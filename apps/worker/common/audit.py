"""compute_runs audit — every Modal job, ingest run, and agent tool call records here.

Use as a context manager so the lifecycle (insert at start with status='running',
update at end with status='done'/'failed' + duration_ms + error + JSON metadata)
is symmetric and exception-safe.

    with compute_run("ingest_fx") as run:
        rows = do_work()
        run.set_output({"rows_inserted": rows})
"""

from __future__ import annotations

import json
import time
import traceback
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg

from .db import connect


class _ComputeRun:
    """Mutable handle the caller uses to attach output metadata before commit."""

    def __init__(self, run_id: UUID, kind: str) -> None:
        self.id = run_id
        self.kind = kind
        self._input: dict[str, Any] | None = None
        self._output: dict[str, Any] | None = None

    def set_input(self, payload: dict[str, Any]) -> None:
        self._input = payload

    def set_output(self, payload: dict[str, Any]) -> None:
        self._output = payload


@contextmanager
def compute_run(kind: str, *, user_id: UUID | None = None):
    """Insert a compute_runs row at start, update on exit.

    On exception, the row gets `status='failed'`, the traceback in `error`,
    and the exception is re-raised so the caller can decide what to do.

    `kind` should follow the spec convention: `ingest_<source>`, `lsm_valuation`,
    `forecast_inference`, `vlstm_train`, `mrs_calibrate`, `agent_tool_call`, etc.
    """
    started = time.monotonic()
    handle: _ComputeRun

    with connect(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into compute_runs (kind, user_id, status, input, created_at)
                values (%s, %s, 'running', %s, now())
                returning id
                """,
                (kind, user_id, json.dumps({})),
            )
            row = cur.fetchone()
            assert row is not None  # INSERT...RETURNING always returns
            handle = _ComputeRun(run_id=row[0], kind=kind)

    try:
        yield handle
    except Exception:
        duration_ms = int((time.monotonic() - started) * 1000)
        with connect(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update compute_runs
                       set status='failed',
                           duration_ms=%s,
                           error=%s,
                           input=%s,
                           output=%s
                     where id=%s
                    """,
                    (
                        duration_ms,
                        traceback.format_exc(limit=20),
                        json.dumps(handle._input or {}),
                        json.dumps(handle._output or {}),
                        handle.id,
                    ),
                )
        raise
    else:
        duration_ms = int((time.monotonic() - started) * 1000)
        with connect(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update compute_runs
                       set status='done',
                           duration_ms=%s,
                           input=%s,
                           output=%s
                     where id=%s
                    """,
                    (
                        duration_ms,
                        json.dumps(handle._input or {}),
                        json.dumps(handle._output or {}),
                        handle.id,
                    ),
                )


def list_recent(kind_prefix: str = "ingest_", limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent compute_runs rows whose `kind` starts with prefix.

    Used by tests and CLI sanity checks. Frontend dashboard reads through
    Supabase JS, not this function.
    """
    with connect() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                select id, kind, status, duration_ms, created_at, error, output
                  from compute_runs
                 where kind like %s
              order by created_at desc
                 limit %s
                """,
                (f"{kind_prefix}%", limit),
            )
            return list(cur.fetchall())
