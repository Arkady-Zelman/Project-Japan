"""Pydantic models for the stack engine — generators, curve steps, clearing rows."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Generator(BaseModel):
    """One unit in the merit-order fleet.

    Mirrors the `generators` table in `001_init.sql`. Loaded from
    `generators_seed.yaml` and UPSERTed via `load_generators.py`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    operator: str | None = None
    area_code: str           # 'TK','KS',… — resolved to area_id at write time.
    unit_type_code: str | None = None  # 'ccgt','steam','ocgt',…
    fuel_type_code: str      # 'lng_ccgt','coal','oil','nuclear',…
    capacity_mw: float = Field(gt=0)
    efficiency: float | None = Field(default=None, gt=0, lt=1.0)
    heat_rate_kj_kwh: float | None = None
    variable_om_jpy_mwh: float | None = Field(default=None, ge=0)
    co2_intensity_t_mwh: float | None = Field(default=None, ge=0)
    # Per-unit override for the fleet-wide _DEFAULT_AVAILABILITY[fuel].
    # Hand-curated where the fleet default is materially wrong (nuclear
    # especially — bimodal across areas). Stored in `generators.metadata`
    # JSONB; build_curve.py reads it from there.
    availability_factor: float | None = Field(default=None, ge=0, le=1.0)
    commissioned: date | None = None
    retired: date | None = None
    notes: str | None = None


class StackCurveStep(BaseModel):
    """One step on the supply curve. Matches the JSON in stack_curves.curve_jsonb."""

    model_config = ConfigDict(extra="forbid")

    mw_cumulative: float
    srmc_jpy_mwh: float
    generator_id: str        # UUID as string — JSONB-friendly
    fuel_code: str
    name: str


class StackClearingRow(BaseModel):
    """Result of clearing the curve against demand."""

    model_config = ConfigDict(extra="forbid")

    area_id: UUID
    slot_start: datetime
    modelled_price_jpy_mwh: float | None
    modelled_demand_mw: float | None
    marginal_unit_id: UUID | None
    stack_curve_id: UUID | None
