"""Retention helpers for bounded Postgres pruning jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

_ALLOWED_RETENTION_TARGETS = {
    ("regime_states", "slot_start"),
    ("generation_mix_actuals", "slot_start"),
    ("demand_actuals", "slot_start"),
    ("jepx_spot_prices", "slot_start"),
    ("weather_obs", "ts"),
    ("stack_clearing_prices", "slot_start"),
    ("stack_curves", "slot_start"),
}

STACK_RETENTION_TABLES = ("stack_clearing_prices", "stack_curves")


def delete_older_than(
    cur: Any,
    conn: Any,
    *,
    table: str,
    column: str,
    cutoff: datetime,
    batch_size: int = 50_000,
    max_batches: int = 500,
) -> int:
    """Delete rows older than ``cutoff`` in bounded batches.

    Table/column names are interpolated because DB drivers cannot bind SQL
    identifiers. Keep the allow-list tight so this helper cannot become a
    generic string-to-SQL escape hatch.
    """

    if (table, column) not in _ALLOWED_RETENTION_TARGETS:
        raise ValueError(f"unsupported retention target: {table}.{column}")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if max_batches < 0:
        raise ValueError("max_batches must be non-negative")

    total = 0
    batches = 0
    while True:
        cur.execute(
            f"""
            delete from {table}
            where ctid in (
              select ctid from {table}
              where {column} < %s
              limit {batch_size}
            )
            """,
            (cutoff,),
        )
        n = cur.rowcount or 0
        conn.commit()
        total += n
        batches += 1
        if n < batch_size or batches > max_batches:
            break
    return total


def delete_old_stack_rows(
    cur: Any,
    conn: Any,
    *,
    cutoff: datetime,
    batch_size: int = 50_000,
    max_batches: int = 500,
) -> dict[str, int]:
    """Prune old stack rows while preserving recent dashboard data.

    ``stack_clearing_prices.stack_curve_id`` references ``stack_curves.id``.
    Delete the child table first, then the parent, so retention does not need a
    destructive TRUNCATE CASCADE.
    """

    deleted: dict[str, int] = {}
    for table in STACK_RETENTION_TABLES:
        deleted[table] = delete_older_than(
            cur,
            conn,
            table=table,
            column="slot_start",
            cutoff=cutoff,
            batch_size=batch_size,
            max_batches=max_batches,
        )
    return deleted
