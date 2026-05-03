"""Pydantic models for seed data — validates rows before they hit Postgres.

Per BUILD_SPEC §15, no untyped data crosses a process boundary. The seed loaders
construct these models from in-memory constants (areas, fuels, unit types) or from
the `holidays` Python package (jp_holidays), then UPSERT into Postgres.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Area(BaseModel):
    """One row of `public.areas`. Codes match BUILD_SPEC §5 line 243."""

    model_config = ConfigDict(extra="forbid")

    code: Literal["TK", "KS", "HK", "TH", "CB", "HR", "CG", "SK", "KY", "SYS"]
    name_en: str = Field(min_length=1)
    name_jp: str | None = None
    tso: str | None = None
    timezone: str = "Asia/Tokyo"


class FuelType(BaseModel):
    """One row of `public.fuel_types`. Codes match BUILD_SPEC §5 line 252."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name_en: str = Field(min_length=1)


class UnitType(BaseModel):
    """One row of `public.unit_types` — generator unit categorisation."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name_en: str = Field(min_length=1)


class JpHoliday(BaseModel):
    """One row of `public.jp_holidays`."""

    model_config = ConfigDict(extra="forbid")

    date: date
    name_jp: str | None = None
    name_en: str | None = None
    category: Literal["national", "obon", "newyear", "goldenweek"]


class DataDictionaryEntry(BaseModel):
    """One row of `public.data_dictionary`. Loaded from YAML at install time
    (and any time a column is added). Read by the AI agent's `describe_schema`
    tool at request time per BUILD_SPEC §9.3 line 1004.
    """

    model_config = ConfigDict(extra="forbid")

    table: str = Field(min_length=1, alias="table")
    column: str = Field(min_length=1)
    description: str = Field(min_length=1)
    unit: str | None = None
    notes: str | None = None
