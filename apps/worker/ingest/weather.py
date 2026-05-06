"""Hourly weather observations from Open-Meteo `/archive` for the 9 JEPX areas.

Schema: weather_obs columns (area_id, ts, temp_c, dewpoint_c, wind_mps,
ghi_w_m2, cloud_pct, forecast_horizon_h, source). PK is
(area_id, ts, forecast_horizon_h, source). For observations we set
forecast_horizon_h=0.

Open-Meteo emits hourly arrays per parameter. We pivot into one row per
(area, hour) and UPSERT.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import httpx
from pydantic import BaseModel, ConfigDict

from common.audit import compute_run
from common.db import connect
from common.lock import advisory_lock
from common.retry import retry_transient

from ._areas import WEATHER_CENTROIDS
from .models import IngestResult

# Variables we ask Open-Meteo for. Names match Open-Meteo's `hourly=` param
# vocabulary. `wind_speed_unit=ms` requests metres-per-second (default is km/h).
_OM_HOURLY_VARS = "temperature_2m,dewpoint_2m,wind_speed_10m,shortwave_radiation,cloud_cover"


class WeatherRow(BaseModel):
    """One row of `weather_obs`."""

    model_config = ConfigDict(extra="forbid")

    area_code: str
    ts: datetime
    temp_c: float | None
    dewpoint_c: float | None
    wind_mps: float | None
    ghi_w_m2: float | None
    cloud_pct: float | None
    forecast_horizon_h: int = 0
    source: str = "open_meteo"


@retry_transient
def _fetch_one_area(area_code: str, lat: float, lon: float, start: date, end: date) -> dict:
    base = os.environ.get(
        "OPEN_METEO_BASE_URL", "https://archive-api.open-meteo.com/v1/archive"
    )
    r = httpx.get(
        base,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            # Open-Meteo's end_date is inclusive; ours is exclusive. Subtract 1 day.
            "end_date": (end if start == end else _yesterday(end)).isoformat(),
            "hourly": _OM_HOURLY_VARS,
            "wind_speed_unit": "ms",
            "timezone": "UTC",
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _yesterday(d: date) -> date:
    from datetime import timedelta
    return d - timedelta(days=1)


def _to_rows(area_code: str, payload: dict) -> list[WeatherRow]:
    h = payload.get("hourly") or {}
    times = h.get("time") or []
    if not times:
        return []
    out: list[WeatherRow] = []
    for i, t in enumerate(times):
        ts = datetime.fromisoformat(t).replace(tzinfo=UTC)
        out.append(
            WeatherRow(
                area_code=area_code,
                ts=ts,
                temp_c=_at(h.get("temperature_2m"), i),
                dewpoint_c=_at(h.get("dewpoint_2m"), i),
                wind_mps=_at(h.get("wind_speed_10m"), i),
                ghi_w_m2=_at(h.get("shortwave_radiation"), i),
                cloud_pct=_at(h.get("cloud_cover"), i),
            )
        )
    return out


def _at(arr: list | None, i: int) -> float | None:
    if not arr or i >= len(arr):
        return None
    v = arr[i]
    return None if v is None else float(v)


def ingest(start: date, end: date) -> IngestResult:
    """Fetch hourly observations for [start, end) for each JEPX area, UPSERT."""
    with compute_run("ingest_weather") as run:
        run.set_input({"start": start.isoformat(), "end": end.isoformat()})

        # Resolve area_code → area_id once.
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select code, id from areas")
                code_to_id: dict[str, object] = dict(cur.fetchall())

        all_rows: list[WeatherRow] = []
        errors: list[str] = []
        for code, (lat, lon) in WEATHER_CENTROIDS.items():
            try:
                payload = _fetch_one_area(code, lat, lon, start, end)
                all_rows.extend(_to_rows(code, payload))
            except Exception as e:
                errors.append(f"{code}: {e!r}")

        inserted = 0
        if all_rows:
            tuples = []
            for row in all_rows:
                area_id = code_to_id.get(row.area_code)
                if not area_id:
                    errors.append(f"unknown area code {row.area_code}")
                    continue
                tuples.append(
                    (
                        area_id, row.ts,
                        row.temp_c, row.dewpoint_c, row.wind_mps,
                        row.ghi_w_m2, row.cloud_pct,
                        row.forecast_horizon_h, row.source,
                    )
                )

            with connect() as conn:
                with conn.cursor() as cur:
                    advisory_lock(cur, "ingest_weather")
                    cur.executemany(
                        """
                        insert into weather_obs
                          (area_id, ts, temp_c, dewpoint_c, wind_mps,
                           ghi_w_m2, cloud_pct, forecast_horizon_h, source)
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        on conflict (area_id, ts, forecast_horizon_h, source) do update set
                          temp_c = excluded.temp_c,
                          dewpoint_c = excluded.dewpoint_c,
                          wind_mps = excluded.wind_mps,
                          ghi_w_m2 = excluded.ghi_w_m2,
                          cloud_pct = excluded.cloud_pct
                        """,
                        tuples,
                    )
                    inserted = cur.rowcount
                conn.commit()

        result = IngestResult(
            source="ingest_weather",
            window_start=start,
            window_end=end,
            rows_fetched=len(all_rows),
            rows_inserted=inserted,
            errors=errors[:50],
        )
        run.set_output(result.model_dump(mode="json", exclude={"errors"}))
        return result
