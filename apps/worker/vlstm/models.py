"""Pydantic models for the VLSTM forecaster — feature windows + forecast rows.

Schemas mirror the DB columns for `forecast_runs` / `forecast_paths` and the
in-memory tensor shapes used during training and inference.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Feature-tensor dimensions (locked).
LOOKBACK_SLOTS = 168          # 3.5 days of half-hour slots.
HORIZON_SLOTS = 48            # 24 hours of half-hour slots.
N_FEATURES = 45               # 8 AR + 9 calendar + 19 fundamentals + 6 exo + 3 regime.
AREA_EMBEDDING_DIM = 8
N_AREAS = 9                   # TK, HK, TH, CB, HR, KS, CG, SK, KY (no SYS).

AreaCode = Literal["TK", "HK", "TH", "CB", "HR", "KS", "CG", "SK", "KY"]


class FeatureWindow(BaseModel):
    """One (X, y, area) example fed to the LSTM.

    `X` is the lookback feature tensor (LOOKBACK_SLOTS × N_FEATURES).
    `y` is the 48-step ahead forecast target (residuals; HORIZON_SLOTS, ).
    `stack_horizon_kwh` is the M4 stack output for the forecast horizon —
    used at inference to reconstruct raw prices via
    `path_kwh = exp(residual_path) * stack_horizon_kwh`. Stored alongside
    so the same `FeatureWindow` is sufficient for both training (only X, y
    needed) and inference (X + stack_horizon_kwh needed).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    area_code: AreaCode
    area_index: int = Field(ge=0, lt=N_AREAS)
    origin: datetime
    # Tensor fields stored as plain `list[list[float]]` here; converters
    # happen in data.py to/from numpy/torch. Keeping pydantic-friendly types
    # avoids serialization gymnastics for the parquet export step.
    X: list[list[float]]
    y: list[float] | None      # None in inference mode (no realised future).
    stack_horizon_kwh: list[float]

    @property
    def n_features(self) -> int:
        return len(self.X[0]) if self.X else 0


class ForecastRunRow(BaseModel):
    """One row in `forecast_runs` — produced by `vlstm/forecast.py` per area."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    model_id: UUID
    area_id: UUID
    forecast_origin: datetime
    horizon_slots: int = HORIZON_SLOTS
    n_paths: int = 1000


class ForecastPathRow(BaseModel):
    """One row in `forecast_paths` — produced by `vlstm/forecast.py`."""

    model_config = ConfigDict(extra="forbid")

    forecast_run_id: UUID
    path_id: int = Field(ge=0)
    slot_start: datetime
    price_jpy_kwh: float
