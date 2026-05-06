"""Local CLI for running ingest jobs without a Modal round-trip.

Usage:

    # Run one source for a single date window
    python -m ingest fx --start 2024-01-01 --end 2024-01-02

    # Run every source for the same window (same path Modal uses)
    python -m ingest backfill --start 2024-01-01 --end 2024-01-02

    # Run a subset of sources
    python -m ingest backfill --start 2024-01-01 --end 2024-01-02 \\
        --sources ingest_fx ingest_weather

The CLI imports the same per-source `ingest()` functions Modal does — there's
no second code path. Useful when iterating on parsing or schema changes; the
turnaround is ~2s vs ~30s for `modal run`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from datetime import date

from common.sentry import init_sentry, tag_source

from .demand import ingest as ingest_demand
from .fx import ingest as ingest_fx
from .generation_mix import ingest as ingest_generation_mix
from .holidays import ingest as ingest_holidays
from .jepx_prices import ingest as ingest_jepx_prices
from .models import IngestResult
from .weather import ingest as ingest_weather

logger = logging.getLogger("ingest")

SOURCES: dict[str, Callable[[date, date], IngestResult]] = {
    "ingest_jepx_prices": ingest_jepx_prices,
    "ingest_demand": ingest_demand,
    "ingest_generation_mix": ingest_generation_mix,
    "ingest_weather": ingest_weather,
    "ingest_fx": ingest_fx,
    "ingest_holidays": ingest_holidays,
}

# Allow short forms on the CLI: `python -m ingest fx ...`
_SHORT_TO_FULL = {name.removeprefix("ingest_"): name for name in SOURCES}


def _resolve(source: str) -> str:
    if source in SOURCES:
        return source
    if source in _SHORT_TO_FULL:
        return _SHORT_TO_FULL[source]
    raise SystemExit(
        f"Unknown source {source!r}. Valid sources: "
        + ", ".join(sorted(SOURCES) + sorted(_SHORT_TO_FULL))
    )


def _run(source_full: str, start: date, end: date) -> IngestResult:
    tag_source(source_full)
    fn = SOURCES[source_full]
    logger.info("running %s for window %s → %s", source_full, start, end)
    result = fn(start, end)
    logger.info(
        "%s done: fetched=%d inserted=%d errors=%d notes=%s",
        source_full,
        result.rows_fetched,
        result.rows_inserted,
        len(result.errors),
        result.notes or "—",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    init_sentry(environment="local")

    parser = argparse.ArgumentParser(prog="python -m ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    one = sub.add_parser("run", help="Run a single ingest source")
    one.add_argument("source", help="Source name (e.g. fx, weather, jepx_prices)")
    one.add_argument("--start", required=True, type=date.fromisoformat)
    one.add_argument("--end", required=True, type=date.fromisoformat)

    bf = sub.add_parser("backfill", help="Run every source (or a subset) for the same window")
    bf.add_argument("--start", required=True, type=date.fromisoformat)
    bf.add_argument("--end", required=True, type=date.fromisoformat)
    bf.add_argument(
        "--sources",
        nargs="*",
        default=None,
        help="Optional subset of source names. Default: all.",
    )

    # Convenience: `python -m ingest fx --start ... --end ...`
    # (parsed as if it were `run fx ...`).
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in {"run", "backfill", "-h", "--help"}:
        argv = ["run", *argv]

    args = parser.parse_args(argv)

    if args.cmd == "run":
        result = _run(_resolve(args.source), args.start, args.end)
        print(json.dumps(result.model_dump(mode="json", exclude={"errors"}), indent=2))
        return 0

    if args.cmd == "backfill":
        wanted = (
            {_resolve(s) for s in args.sources}
            if args.sources
            else set(SOURCES.keys())
        )
        results: dict[str, dict] = {}
        for name in SOURCES:
            if name not in wanted:
                continue
            try:
                r = _run(name, args.start, args.end)
                results[name] = r.model_dump(mode="json", exclude={"errors"})
            except Exception as e:
                logger.exception("%s failed", name)
                results[name] = {"error": repr(e)}
        print(json.dumps(results, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
