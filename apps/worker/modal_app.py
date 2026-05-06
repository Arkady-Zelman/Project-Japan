"""JEPX-Storage Modal app — entry point for all scheduled jobs and HTTP endpoints.

Per BUILD_SPEC §11, this is a single Modal app with multiple functions sharing
one image. Tokyo region is set at the workspace level (not per-function).

Functions in this file:

  healthcheck                 — M1 sanity check, kept for diagnostics.
  ingest_daily                — daily 21:00 UTC = 06:00 JST. Fans out to each
                                 ingest source for [yesterday, today).
  ingest_holidays_annual      — Jan 1 00:05 JST. Refreshes the holiday window.
  ingest_backfill             — on-demand. Iterates source × monthly chunks.

Modal Secrets:
  - jepx-supabase   — SUPABASE_DB_URL, SUPABASE_AGENT_READONLY_DB_URL,
                       SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENAI_API_KEY,
                       FRANKFURTER_BASE_URL, OPEN_METEO_BASE_URL,
                       OPEN_METEO_FORECAST_URL, JAPANESEPOWER_BASE_URL,
                       CME_BASE_URL, SENTRY_DSN.
                       Operator creates this in the Modal dashboard with
                       `modal secret create jepx-supabase --from-dotenv apps/worker/.env`.

The actual ingest implementations live in `apps/worker/ingest/<source>.py` and
share infrastructure from `apps/worker/common/`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import modal

app = modal.App("jepx-storage")

# Shared image used by every function in this app. Python 3.12 per BUILD_SPEC
# §11 line 1087. Worker source mounted at /root via add_local_python_source.
base_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "modal>=0.64",
        "pydantic>=2.7",
        "python-dotenv>=1.0",
        "psycopg[binary]>=3.2.13",
        "holidays>=0.50",
        "pyyaml>=6.0",
        "httpx>=0.27",
        "tenacity>=8.4",
        "pandas>=2.2",
        "sentry-sdk>=2.0",
    )
    .add_local_python_source("common", "ingest", "seed")
)

# Secret group injected as env vars at runtime. Created by the operator in the
# Modal dashboard before the first cron firing.
_secrets = [modal.Secret.from_name("jepx-supabase")]


# ---------------------------------------------------------------------------
# Healthcheck
# ---------------------------------------------------------------------------


@app.function(image=base_image)
def healthcheck() -> str:
    """Sanity check that the Modal app is deployable. Run via `modal run`."""
    return "ok"


# ---------------------------------------------------------------------------
# Daily ingest fan-out
# ---------------------------------------------------------------------------

# 21:00 UTC = 06:00 JST per BUILD_SPEC §11 line 1108. Fires once a day.
_DAILY_CRON = modal.Cron("0 21 * * *")


@app.function(image=base_image, cpu=2.0, timeout=900, schedule=_DAILY_CRON, secrets=_secrets)
def ingest_daily() -> dict[str, dict]:
    """Run all M3 ingest jobs for [yesterday, today). Returns per-source results."""
    from common.sentry import init_sentry, tag_source

    init_sentry()

    today = datetime.now(tz=UTC).date()
    yesterday = today - timedelta(days=1)

    results: dict[str, dict] = {}
    for source_name, ingest_fn in _DAILY_SOURCES.items():
        tag_source(source_name)
        try:
            r = ingest_fn(yesterday, today)
            results[source_name] = r.model_dump(mode="json", exclude={"errors"})
        except Exception as e:
            # Don't abort the whole fan-out on a single source failure.
            # compute_runs already records the failure inside ingest_fn's
            # `with compute_run(...)`, plus Sentry catches the exception.
            results[source_name] = {"error": repr(e)}
    return results


# ---------------------------------------------------------------------------
# Annual holiday refresh
# ---------------------------------------------------------------------------

# 00:05 UTC on Jan 1 ≈ 09:05 JST on Jan 1. Close enough; spec doesn't pin it.
_ANNUAL_HOLIDAYS_CRON = modal.Cron("5 0 1 1 *")


@app.function(image=base_image, schedule=_ANNUAL_HOLIDAYS_CRON, secrets=_secrets)
def ingest_holidays_annual() -> dict:
    """Refresh holidays for the next 8 years on Jan 1. Idempotent."""
    from common.sentry import init_sentry
    from ingest.holidays import ingest as ingest_holidays

    init_sentry()
    this_year = datetime.now(tz=UTC).year
    r = ingest_holidays(date(this_year, 1, 1), date(this_year + 8, 1, 1))
    return r.model_dump(mode="json", exclude={"errors"})


# ---------------------------------------------------------------------------
# Historical backfill (on-demand)
# ---------------------------------------------------------------------------


@app.function(image=base_image, cpu=2.0, timeout=3600, secrets=_secrets)
def ingest_backfill(
    start_iso: str,
    end_iso: str,
    sources: str = "",
) -> dict[str, dict]:
    """Run each source's `ingest()` over the requested window.

    The window is passed wholesale to each source — no per-source chunking
    here, because each upstream is a single bulk fetch (jepxSpot.csv,
    demand.csv) or a small handful of HTTP calls (weather, fx). If a source
    grows to where this becomes slow, we'll add monthly chunking.

    Invoke via:

        modal run apps/worker/modal_app.py::ingest_backfill \\
          --start-iso 2020-01-01 --end-iso 2026-01-01

    Optionally restrict to a comma-separated subset (Modal's CLI doesn't accept
    list[str] annotations, hence the comma-string form):

        modal run apps/worker/modal_app.py::ingest_backfill \\
          --start-iso 2024-01-01 --end-iso 2024-02-01 \\
          --sources ingest_fx,ingest_weather
    """
    from common.sentry import init_sentry, tag_source

    init_sentry()
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    requested = {s.strip() for s in sources.split(",") if s.strip()} if sources else set()
    selected = (
        {name: fn for name, fn in _DAILY_SOURCES.items() if name in requested}
        if requested
        else _DAILY_SOURCES
    )

    results: dict[str, dict] = {}
    for source_name, ingest_fn in selected.items():
        tag_source(source_name)
        try:
            r = ingest_fn(start, end)
            results[source_name] = r.model_dump(mode="json", exclude={"errors"})
        except Exception as e:
            results[source_name] = {"error": repr(e)}
    return results


# ---------------------------------------------------------------------------
# Local entry points (for `modal run` to bind to a callable)
# ---------------------------------------------------------------------------


@app.local_entrypoint()
def run_healthcheck() -> None:
    """`modal run apps/worker/modal_app.py::run_healthcheck`"""
    print(healthcheck.remote())


@app.local_entrypoint()
def run_ingest_daily() -> None:
    """`modal run apps/worker/modal_app.py::run_ingest_daily`"""
    import json

    print(json.dumps(ingest_daily.remote(), indent=2, default=str))


# ---------------------------------------------------------------------------
# Lazy import of the per-source ingest functions.
# Module-level imports are deferred to runtime via this dict so that
# `modal deploy` can serialize the app without first installing the worker
# image's deps locally.
# ---------------------------------------------------------------------------


def _load_sources():
    from ingest.demand import ingest as ingest_demand
    from ingest.fx import ingest as ingest_fx
    from ingest.generation_mix import ingest as ingest_generation_mix
    from ingest.holidays import ingest as ingest_holidays
    from ingest.jepx_prices import ingest as ingest_jepx_prices
    from ingest.weather import ingest as ingest_weather

    return {
        "ingest_jepx_prices": ingest_jepx_prices,
        "ingest_demand": ingest_demand,
        "ingest_generation_mix": ingest_generation_mix,
        "ingest_weather": ingest_weather,
        "ingest_fx": ingest_fx,
        "ingest_holidays": ingest_holidays,
    }


# Populated lazily inside Modal containers. Module-level access is fine because
# imports are local to `_load_sources()`. We resolve once and cache.
class _SourcesProxy:
    """Lazy dict-like proxy that loads ingest modules on first access."""

    _cache: dict | None = None

    def _resolve(self) -> dict:
        if self._cache is None:
            self._cache = _load_sources()
        return self._cache

    def __iter__(self):
        return iter(self._resolve())

    def __getitem__(self, key):
        return self._resolve()[key]

    def items(self):
        return self._resolve().items()

    def values(self):
        return self._resolve().values()


_DAILY_SOURCES = _SourcesProxy()
