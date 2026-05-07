"""Pydantic models for the regime engine — calibrated model rows + regime states."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RegimeLabel = Literal["base", "spike", "drop"]


class CalibratedModel(BaseModel):
    """In-memory representation of one area's calibrated MRS, before persisting.

    Mirrors the `models` table columns we write. The full `hyperparams` JSON
    has the regime means/variances/transition matrix and the index→label
    mapping that `infer_state.py` reads back.
    """

    model_config = ConfigDict(extra="forbid")

    area_code: str
    name: str                         # e.g., 'mrs_TK'
    type: Literal["mrs"] = "mrs"
    version: str                      # e.g., 'v1-2026-05-07'
    hyperparams: dict
    training_window_start: date
    training_window_end: date
    metrics: dict                     # log-likelihood, AIC, BIC, n_observations
    status: Literal["ready", "deprecated"] = "ready"


class RegimeStateRow(BaseModel):
    """One slot of posterior regime probabilities."""

    model_config = ConfigDict(extra="forbid")

    area_id: UUID
    slot_start: datetime
    p_base: float = Field(ge=0, le=1)
    p_spike: float = Field(ge=0, le=1)
    p_drop: float = Field(ge=0, le=1)
    most_likely_regime: RegimeLabel
    model_version: str
