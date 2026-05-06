"""Sentry SDK initialization — no-op when SENTRY_DSN is unset.

Local development typically runs without Sentry. Modal scheduled functions and
HTTP endpoints initialize Sentry once at module load so uncaught exceptions
get reported with stack traces. Each ingest job should add a `source` tag for
filterability.
"""

from __future__ import annotations

import os

import sentry_sdk

from .db import _ensure_env_loaded

_INITIALIZED = False


def init_sentry(*, environment: str = "production") -> bool:
    """Initialize the global Sentry SDK if SENTRY_DSN is set.

    Returns True if Sentry was actually initialized, False if no-op.
    Idempotent — safe to call multiple times.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return True
    _ensure_env_loaded()
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=0.0,  # No tracing for ingest yet — just errors.
        send_default_pii=False,
    )
    _INITIALIZED = True
    return True


def tag_source(source: str) -> None:
    """Tag the current Sentry scope with a `source` (the ingest job name)."""
    sentry_sdk.set_tag("source", source)
