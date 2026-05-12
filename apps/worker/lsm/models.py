"""Pydantic schemas for the LSM engine — asset spec + valuation result."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssetSpec(BaseModel):
    """Asset specification fed to `engine.run_lsm`.

    Mirrors the `assets` table columns where possible. Some fields use
    the paper's convention (separate charge/discharge rate limits) for
    tests; production assets typically have symmetric `power_mw`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = "anonymous"
    asset_type: Literal[
        "bess_li_ion", "pumped_hydro", "compressed_air", "gas_storage"
    ] = "bess_li_ion"

    # Energy and SoC bounds in MWh.
    energy_mwh: float = Field(gt=0)
    soc_min_mwh: float = Field(ge=0)
    soc_max_mwh: float = Field(gt=0)
    soc_initial_mwh: float = Field(ge=0)

    # Power rate limits — separate charge/discharge to support the paper's
    # asymmetric gas-storage spec. For symmetric BESS, set both to the
    # same value.
    power_mw_charge: float = Field(gt=0)         # +∆v rate (charging)
    power_mw_discharge: float = Field(gt=0)      # |-∆v| rate (discharging)

    # Round-trip efficiency in [0, 1]. The engine splits this symmetrically:
    # losses on charge AND losses on discharge use sqrt(eff). 1.0 = no loss.
    round_trip_eff: float = Field(gt=0, le=1, default=1.0)

    # Variable cost in JPY per MWh of throughput (charge OR discharge).
    # Models battery degradation, pumped-hydro O&M, etc.
    degradation_jpy_mwh: float = Field(ge=0, default=0.0)

    # Cycle-limit constraint: cumulative throughput must not exceed
    # max_cycles_per_year × energy_mwh × (T·dt_days / 365). Setting this
    # to a very high number effectively removes the constraint.
    max_cycles_per_year: float = Field(gt=0, default=10_000.0)


class ValuationResult(BaseModel):
    """Return shape of `engine.run_lsm` (Pydantic mirror of the in-memory tuple)."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    total_jpy: float
    intrinsic_jpy: float
    extrinsic_jpy: float
    ci_lower_jpy: float       # 5th percentile of per-path totals
    ci_upper_jpy: float       # 95th percentile
    n_paths: int
    n_volume_grid: int
    runtime_seconds: float

    # Per-slot decision summaries. The engine returns full (M, T+1) and
    # (M, T) arrays internally; the Pydantic surface keeps a slot-level
    # summary suitable for `valuation_decisions` table rows.
    slot_mean_soc_mwh: list[float]
    slot_mean_action_mw: list[float]
    slot_expected_pnl_jpy: list[float]
