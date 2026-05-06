"""Shared types for ingest jobs.

`IngestResult` is what every `ingest(start, end)` function returns. The fields
are deliberately small — detailed audit goes through `compute_runs` (via
`common.audit.compute_run`), not through this return value.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class IngestResult(BaseModel):
    """Outcome of one `ingest(start, end)` call."""

    model_config = ConfigDict(extra="forbid")

    source: str               # e.g. "ingest_fx"
    window_start: date
    window_end: date
    rows_fetched: int = 0     # raw rows from upstream
    rows_inserted: int = 0    # rows after UPSERT (rowcount = insert + update)
    errors: list[str] = []    # per-row Pydantic failures, capped to 50
    notes: str | None = None  # free-form diagnostic, e.g. "v1 source unavailable"
