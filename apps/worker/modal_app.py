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
        "numpy>=1.26",
        "statsmodels>=0.14",
        # M6 — VLSTM forecaster (training on GPU L4, inference on CPU).
        # torch + lightning + pyarrow (training-tensor parquet export).
        "torch>=2.3,<2.6",
        "pytorch-lightning>=2.1",
        "pyarrow>=14",
        # M7 — LSM storage valuation. Numba JIT with parallel=True is
        # mandatory; without it the engine is unusably slow. FastAPI is
        # required for @modal.fastapi_endpoint (the lsm-value HTTP route).
        "numba>=0.59",
        "fastapi[standard]>=0.115",
        # M9 — AI Analyst. OpenAI SDK + sqlglot for SELECT-only SQL guard +
        # scikit-learn for fit_quick_model + sse-starlette for streaming
        # responses out of the agent ASGI app.
        "openai>=1.50",
        "sqlglot>=23",
        "scikit-learn>=1.5",
        "sse-starlette>=2.1",
    )
    .add_local_python_source(
        "common", "ingest", "seed", "stack", "regime", "vlstm", "lsm",
        "backtest", "demo",
        # M9 agent shelved 2026-05-10 — see SESSION_LOG_2026-05-10-M9.md.
        # The Python sources (apps/worker/agent/*.py) are intact on disk.
        # To resume: re-add "agent" to this list and uncomment agent_app
        # below, then `modal deploy`. OpenAI quota is the prerequisite.
        # "agent",
    )
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
# Annual holiday refresh — manual-only on the free Modal tier (5-cron cap).
# Operator runs `modal run apps/worker/modal_app.py::ingest_holidays_annual`
# on Jan 1 each year, OR sets a workspace-level reminder. Holidays are loaded
# 8 years ahead so the manual cadence is forgiving.
# ---------------------------------------------------------------------------


@app.function(image=base_image, secrets=_secrets)
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
# Stack engine — daily build + on-demand backfill (M4)
# ---------------------------------------------------------------------------

# 21:30 UTC = 06:30 JST. Fires 30 min after `ingest_daily` so all the
# input tables are fresh.
_STACK_DAILY_CRON = modal.Cron("30 21 * * *")


@app.function(image=base_image, cpu=2.0, timeout=900, schedule=_STACK_DAILY_CRON, secrets=_secrets)
def stack_run_daily() -> dict:
    """Build merit-order curves for yesterday across every area.

    Also fires the public-demo refresh (`demo_daily`) so the /workbench and
    /lab pages always show last-24h results without needing a real user
    session. Demo is fire-and-forget (`.spawn`) so stack runtime isn't
    affected by LSM/backtest latency.
    """
    from common.sentry import init_sentry
    from stack.build_curve import build_window

    init_sentry()
    today = datetime.now(tz=UTC).date()
    yesterday = today - timedelta(days=1)
    out = build_window(yesterday, today)

    try:
        demo_daily.spawn()
        out["demo_spawned"] = True
    except Exception as e:  # noqa: BLE001
        out["demo_spawned"] = f"error: {e}"
    return out


# ---------------------------------------------------------------------------
# Demo daily refresh — public /workbench + /lab examples
# ---------------------------------------------------------------------------

# Not on its own schedule (would exceed Modal's 5-cron free-tier cap).
# Spawned from stack_run_daily so it fires automatically every 06:30 JST.
# Operator can also run on demand:
#   modal run apps/worker/modal_app.py::demo_daily_run
@app.function(image=base_image, cpu=4.0, timeout=1800, secrets=_secrets)
def demo_daily() -> dict:
    """Refresh the public demo: LSM valuation + 4-strategy backtest."""
    from common.sentry import init_sentry
    from demo.run_daily import run as run_demo

    init_sentry()
    return run_demo()


@app.function(image=base_image, cpu=4.0, timeout=1800, secrets=_secrets)
def demo_daily_run() -> dict:
    """On-demand variant of `demo_daily` for `modal run` invocations."""
    from common.sentry import init_sentry
    from demo.run_daily import run as run_demo

    init_sentry()
    return run_demo()


@app.function(image=base_image, cpu=4.0, timeout=3600, secrets=_secrets)
def stack_backfill(
    start_iso: str,
    end_iso: str,
    areas: str = "",
) -> dict:
    """On-demand stack build over a window. Same code path as daily.

    Invoke via:

        modal run apps/worker/modal_app.py::stack_backfill \\
          --start-iso 2023-01-01 --end-iso 2024-04-01

    Optional area subset (comma-separated):

        modal run apps/worker/modal_app.py::stack_backfill \\
          --start-iso 2024-04-01 --end-iso 2026-05-01 --areas TK,KS
    """
    from common.sentry import init_sentry
    from stack.build_curve import build_window

    init_sentry()
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    selected = [a.strip() for a in areas.split(",") if a.strip()] or None
    return build_window(start, end, selected)


# ---------------------------------------------------------------------------
# Regime engine — weekly recalibration + on-demand backfill (M5)
# ---------------------------------------------------------------------------

# 18:00 UTC Sun = 03:00 JST Mon. Per spec §7.4 the MRS recalibrates weekly.
# After ingest_daily + stack_run_daily have populated the previous week's
# residuals. This single cron bundles all four weekly model jobs to stay
# inside Modal's 5-cron free-tier cap — each step still emits its own
# compute_run row so the dashboard sees them individually.
_MODELS_WEEKLY_CRON = modal.Cron("0 18 * * 0")


@app.function(image=base_image, cpu=4.0, timeout=3600,
              schedule=_MODELS_WEEKLY_CRON, secrets=_secrets)
def models_weekly() -> dict:
    """Weekly bundle: MRS calibrate → MRS infer → MRS validate → VLSTM train.

    Each step wraps in its own `compute_run(...)` so the dashboard shows
    one green dot per kind per week. Failures in early steps don't block
    later ones — the bundle keeps going and reports per-step status.

    The VLSTM step delegates to `train_vlstm_weekly.remote()` so the GPU
    L4 only spins up for the training portion — the regime jobs run on
    this CPU container.
    """
    from common.sentry import init_sentry

    init_sentry()

    today = datetime.now(tz=UTC).date()
    tomorrow = today + timedelta(days=1)
    out: dict[str, dict | str] = {}

    # 1) Regime MRS calibration (emits regime_calibrate).
    try:
        from regime.mrs_calibrate import run_all as mrs_calibrate_run_all
        out["regime_calibrate"] = mrs_calibrate_run_all(date(2023, 1, 1), tomorrow)
    except Exception as e:  # noqa: BLE001
        out["regime_calibrate"] = {"error": str(e)}

    # 2) Regime state inference (emits regime_infer).
    try:
        from regime.infer_state import run_all as infer_run_all
        # Infer for the most-recent month so the dashboard always has fresh
        # posteriors without re-inferring all of history every week.
        infer_start = today - timedelta(days=35)
        out["regime_infer"] = infer_run_all(infer_start, tomorrow)
    except Exception as e:  # noqa: BLE001
        out["regime_infer"] = {"error": str(e)}

    # 3) Regime gate validation (emits regime_validate).
    try:
        from regime.validate import evaluate as regime_evaluate
        # Same recent-month window as inference — the gate replays it.
        out["regime_validate"] = regime_evaluate(today - timedelta(days=35), tomorrow)
    except Exception as e:  # noqa: BLE001
        out["regime_validate"] = {"error": str(e)}

    # 4) VLSTM weekly retrain on GPU L4 (emits vlstm_train).
    try:
        out["vlstm_train"] = train_vlstm_weekly.remote()
    except Exception as e:  # noqa: BLE001
        out["vlstm_train"] = {"error": str(e)}

    return out


# Kept for one-off operator runs / backfills.
@app.function(image=base_image, cpu=4.0, timeout=3600, secrets=_secrets)
def regime_calibrate_weekly() -> dict:
    """On-demand MRS calibration only (no infer/validate/vlstm). Pre-bundle behavior."""
    from common.sentry import init_sentry
    from regime.mrs_calibrate import run_all

    init_sentry()
    start = date(2023, 1, 1)
    end = datetime.now(tz=UTC).date() + timedelta(days=1)
    return run_all(start, end)


@app.function(image=base_image, cpu=4.0, timeout=3600, secrets=_secrets)
def regime_calibrate_run(start_iso: str = "", end_iso: str = "") -> dict:
    """On-demand calibration for a custom window (or default 2023-01-01 → tomorrow)."""
    from common.sentry import init_sentry
    from regime.mrs_calibrate import run_all

    init_sentry()
    start = date.fromisoformat(start_iso) if start_iso else date(2023, 1, 1)
    end = (
        date.fromisoformat(end_iso) if end_iso
        else datetime.now(tz=UTC).date() + timedelta(days=1)
    )
    return run_all(start, end)


# ---------------------------------------------------------------------------
# VLSTM forecaster — weekly L4 training + twice-daily CPU inference (M6)
# ---------------------------------------------------------------------------

# 22:00 UTC = 07:00 JST and 13:00 UTC = 22:00 JST per BUILD_SPEC §7.6.
_VLSTM_FORECAST_MORNING_CRON = modal.Cron("0 22 * * *")
_VLSTM_FORECAST_EVENING_CRON = modal.Cron("0 13 * * *")


# VLSTM weekly retrain is manual-only on the free Modal tier (5-cron cap).
# Operator runs `modal run apps/worker/modal_app.py::train_vlstm_weekly` each
# week, OR upgrades the workspace plan and re-adds the schedule decorator.


@app.function(image=base_image, gpu="L4", cpu=4.0, timeout=3600, secrets=_secrets)
def train_vlstm_weekly() -> dict:
    """Weekly VLSTM retrain on Modal GPU L4.

    Runs the full pipeline: feature extraction → Lightning fit → AR(1)
    baseline comparison → gate decision → models row + weights save.
    Falls back to default region if Tokyo doesn't have L4 capacity.
    """
    from common.sentry import init_sentry
    from vlstm.train import train

    init_sentry()
    today = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return train(
        train_start=datetime(2024, 1, 1, tzinfo=UTC),
        gate_start=today - timedelta(days=14),
        gate_end=today,
        n_epochs=25,
        stride=4,
    )


@app.function(image=base_image, cpu=2.0, timeout=600, secrets=_secrets)
def forecast_vlstm_run() -> dict:
    """On-demand forecast inference at the current top-of-half-hour."""
    from common.sentry import init_sentry
    from vlstm.forecast import run_inference

    init_sentry()
    return run_inference()


@app.function(image=base_image, cpu=2.0, timeout=600,
              schedule=_VLSTM_FORECAST_MORNING_CRON, secrets=_secrets)
def forecast_vlstm_morning() -> dict:
    """07:00 JST forecast — same body as `forecast_vlstm_run`."""
    from common.sentry import init_sentry
    from vlstm.forecast import run_inference

    init_sentry()
    return run_inference()


# Evening forecast schedule dropped 2026-05-13 to make room within Modal's
# 5-cron free-tier cap for the demo daily refresh. Morning forecast
# (07:00 JST) still runs automatically; operator can fire the evening one
# on demand via `modal run apps/worker/modal_app.py::forecast_vlstm_run`.
@app.function(image=base_image, cpu=2.0, timeout=600, secrets=_secrets)
def forecast_vlstm_evening() -> dict:
    """22:00 JST forecast — same body as `forecast_vlstm_run`."""
    from common.sentry import init_sentry
    from vlstm.forecast import run_inference

    init_sentry()
    return run_inference()


# ---------------------------------------------------------------------------
# LSM storage valuation engine — operator-triggered HTTP endpoint (M7)
# ---------------------------------------------------------------------------

# Per BUILD_SPEC §7.7, LSM is a Modal HTTP endpoint, NOT a scheduled job.
# Frontend POSTs to it with `{valuation_id}`; the function loads the queued
# row, runs the LSM, persists results, returns the headline numbers.
# Numba `parallel=True` requires the cpu=4.0 allocation to actually
# parallelise across cores.


@app.function(image=base_image, cpu=4.0, timeout=600, secrets=_secrets)
@modal.fastapi_endpoint(method="POST", label="lsm-value")
def lsm_value(payload: dict) -> dict:
    """On-demand LSM valuation. Body: `{"valuation_id": "<uuid>"}`.

    Returns the headline numbers; full per-slot decisions are written to
    `valuation_decisions` and the row is updated to `status='done'` so the
    frontend can subscribe via Realtime.
    """
    from uuid import UUID

    from common.sentry import init_sentry
    from lsm.runner import mark_failed, run_valuation

    init_sentry()
    valuation_id_str = payload.get("valuation_id")
    if not valuation_id_str:
        return {"error": "valuation_id required"}
    try:
        vid = UUID(str(valuation_id_str))
    except ValueError:
        return {"error": f"invalid uuid: {valuation_id_str}"}
    try:
        result = run_valuation(vid)
    except Exception as e:
        mark_failed(vid, repr(e))
        raise
    return result.model_dump(mode="json")


@app.function(image=base_image, cpu=4.0, timeout=600, secrets=_secrets)
def lsm_value_run(valuation_id: str) -> dict:
    """On-demand local-runner variant for `modal run` invocations.

    Same body as the HTTP endpoint; useful for the operator demo
    (`modal run apps/worker/modal_app.py::lsm_value_run --valuation-id ...`)
    without needing to set up the public URL.
    """
    from uuid import UUID

    from common.sentry import init_sentry
    from lsm.runner import mark_failed, run_valuation

    init_sentry()
    vid = UUID(valuation_id)
    try:
        result = run_valuation(vid)
    except Exception as e:
        mark_failed(vid, repr(e))
        raise
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Backtest engine — operator-triggered HTTP endpoint (M8)
# ---------------------------------------------------------------------------


@app.function(image=base_image, cpu=4.0, timeout=900, secrets=_secrets)
@modal.fastapi_endpoint(method="POST", label="run-backtest")
def run_backtest(payload: dict) -> dict:
    """On-demand strategy backtest. Body: `{"backtest_id": "<uuid>", "spread_jpy_kwh": 2.0?}`.

    Returns the headline metrics; full per-slot trade rows are persisted
    in `backtests.trades_jsonb` and the row updates to `status='done'`
    so the frontend can subscribe via Realtime.
    """
    from uuid import UUID

    from backtest.runner import mark_failed
    from backtest.runner import run_backtest as _run_backtest
    from common.sentry import init_sentry

    init_sentry()
    backtest_id_str = payload.get("backtest_id")
    if not backtest_id_str:
        return {"error": "backtest_id required"}
    try:
        bid = UUID(str(backtest_id_str))
    except ValueError:
        return {"error": f"invalid uuid: {backtest_id_str}"}
    spread = float(payload.get("spread_jpy_kwh", 2.0))
    naive_buy = payload.get("naive_buy_threshold_jpy_kwh")
    naive_sell = payload.get("naive_sell_threshold_jpy_kwh")
    try:
        result = _run_backtest(
            bid,
            spread_jpy_kwh=spread,
            naive_buy=float(naive_buy) if naive_buy is not None else None,
            naive_sell=float(naive_sell) if naive_sell is not None else None,
        )
    except Exception as e:
        mark_failed(bid, repr(e))
        raise
    return result.model_dump(mode="json")


@app.function(image=base_image, cpu=4.0, timeout=900, secrets=_secrets)
def run_backtest_run(backtest_id: str, spread_jpy_kwh: float = 2.0) -> dict:
    """`modal run` variant of `run_backtest`. Same body."""
    from uuid import UUID

    from backtest.runner import mark_failed
    from backtest.runner import run_backtest as _run_backtest
    from common.sentry import init_sentry

    init_sentry()
    bid = UUID(backtest_id)
    try:
        result = _run_backtest(bid, spread_jpy_kwh=spread_jpy_kwh)
    except Exception as e:
        mark_failed(bid, repr(e))
        raise
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# AI Analyst — FastAPI ASGI service (M9) — SHELVED 2026-05-10
# ---------------------------------------------------------------------------

# Shelved on 2026-05-10 because the operator's OpenAI account hit
# `429 insufficient_quota` on the first end-to-end /chat call. The
# pipeline (sqlglot + agent_readonly role + ASGI + SSE + Realtime +
# scratchpad) is structurally verified end-to-end; the §13 smoke-test
# scenarios pend operator OpenAI credit top-up. To resume:
#   1. Re-add "agent" to add_local_python_source above.
#   2. Uncomment the @app.function block below.
#   3. `modal deploy modal_app.py`.
#   4. Verify `https://projectjapan--agent.modal.run/health` returns 200,
#      then run the §13 smoke-test scenarios in /analyst.
# See SESSION_LOG_2026-05-10-M9.md for full context.

# @app.function(
#     image=base_image, cpu=2.0, timeout=300, secrets=_secrets,
#     max_containers=10,
# )
# @modal.asgi_app(label="agent")
# def agent_app():
#     from common.sentry import init_sentry
#
#     init_sentry()
#     from agent.service import build_app
#     return build_app()


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
    from ingest.fuel_prices import ingest as ingest_fuel_prices
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
        "ingest_fuel_prices": ingest_fuel_prices,
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
