"""Guards the JST-dated TSO file vs UTC ingest-window contract.

Tohoku daily CSVs are named by JST calendar date and contain 00:00–23:30 JST
only. `ingest_daily` asks for a UTC [yesterday, today) window. Fetching only
the UTC date's JST file and filtering to that UTC date permanently drops
15:00–23:30 UTC (JST next-calendar-morning) every day — 17 half-hour slots
of demand and generation mix. When the monthly file is unpublished (verified
2026-09 for TH), that hole is live and starves the TH stack / VLSTM lookback.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from ingest._area_supply import (
    AREA_SOURCES,
    _MONTHLY_TEPCO_FMT_V2,
    _jst_dated_files_for_utc_window,
    _months_between,
    _parse_rows,
)


def _jst_day_frame(jst_day: date) -> pd.DataFrame:
    """48 half-hour slots for one JST calendar day, matching V2 monthly columns."""
    rows = []
    midnight = datetime(jst_day.year, jst_day.month, jst_day.day)
    for i in range(48):
        ts = midnight + timedelta(minutes=30 * i)
        row = {col: 0.0 for col in _MONTHLY_TEPCO_FMT_V2.columns}
        row["DATE"] = ts.strftime("%Y/%m/%d")
        row["TIME"] = f"{ts.hour}:{ts.minute:02d}"
        row["demand"] = 1000 + i
        rows.append(row)
    return pd.DataFrame(rows)


def test_jst_files_for_one_utc_day_include_next_jst_morning() -> None:
    files = _jst_dated_files_for_utc_window(date(2026, 9, 10), date(2026, 9, 11))
    assert files == [date(2026, 9, 10), date(2026, 9, 11)]


def test_months_between_includes_next_month_at_month_end() -> None:
    assert _months_between(date(2026, 9, 11), date(2026, 9, 12)) == [(2026, 9)]
    assert _months_between(date(2026, 9, 30), date(2026, 10, 1)) == [
        (2026, 9),
        (2026, 10),
    ]


def test_single_jst_file_filtered_to_utc_day_drops_evening_slots() -> None:
    """Documents the hole the old daily loop produced.

    JST 2026-09-10 00:00–23:30 = UTC 2026-09-09 15:00 – 2026-09-10 14:30.
    Filtering that file to UTC [2026-09-10, 2026-09-11) keeps only
    00:00–14:30 UTC (30 slots) and drops the 17 evening slots.
    """
    src = AREA_SOURCES["TH"]
    parsed = _parse_rows(
        _jst_day_frame(date(2026, 9, 10)),
        src,
        _MONTHLY_TEPCO_FMT_V2,
        date(2026, 9, 10),
        date(2026, 9, 11),
    )
    starts = [r.slot_start for r in parsed]
    assert len(starts) == 30
    assert min(starts) == datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    assert max(starts) == datetime(2026, 9, 10, 14, 30, tzinfo=UTC)


def test_two_jst_files_cover_full_utc_day() -> None:
    src = AREA_SOURCES["TH"]
    start, end = date(2026, 9, 10), date(2026, 9, 11)
    parsed: list = []
    for jst_day in _jst_dated_files_for_utc_window(start, end):
        parsed.extend(
            _parse_rows(
                _jst_day_frame(jst_day),
                src,
                _MONTHLY_TEPCO_FMT_V2,
                start,
                end,
            )
        )
    starts = sorted(r.slot_start for r in parsed)
    assert len(starts) == 48
    assert starts[0] == datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    assert starts[-1] == datetime(2026, 9, 10, 23, 30, tzinfo=UTC)
    expected = [
        datetime(2026, 9, 10, 0, 0, tzinfo=UTC) + timedelta(minutes=30 * i)
        for i in range(48)
    ]
    assert starts == expected
