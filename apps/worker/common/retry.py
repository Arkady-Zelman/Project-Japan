"""Tenacity-backed retry decorator for transient HTTP / DB errors.

Spec §7.2 line 843: 5 attempts max, exponential backoff with jitter, retry
only on transient classes — connection errors, timeouts, OperationalError.

We DO NOT retry:
  - 4xx HTTP responses (bug or auth issue, retrying won't help)
  - psycopg.IntegrityError (UPSERT already handles duplicates; retry would
    just hit the same constraint)
  - psycopg.ProgrammingError (SQL bug — retry won't help)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import httpx
import psycopg
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

T = TypeVar("T")

_TRANSIENT = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
    psycopg.OperationalError,
)


def retry_transient(fn: Callable[..., T]) -> Callable[..., T]:
    """Decorator: retry the wrapped function on transient errors.

    5 attempts, exponential backoff (1s, 2s, 4s, 8s) with random jitter up to 1s.
    """
    def wrapper(*args, **kwargs) -> T:
        for attempt in Retrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential_jitter(initial=1, max=30, jitter=1),
            retry=retry_if_exception_type(_TRANSIENT),
            reraise=True,
        ):
            with attempt:
                return fn(*args, **kwargs)
        raise RuntimeError("unreachable: tenacity always raises or returns")

    wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper
