"""Peaks-over-threshold (POT) tail estimator for the spike side of the residual.

What this fixes
---------------
Per the M5 diagnostic in `SESSION_LOG_2026-05-07.md` and the spike-research
report (2026-05-07), a 3-regime symmetric-Gaussian MRS has a well-known
pathology when residuals are skewed: EM allocates regimes to where the *mass*
is, and a sparse one-sided tail (e.g., 40 positive-residual spike slots in TH
April 2026 vs hundreds of negative-residual oversupply slots) gets no regime
of its own. Posterior P(spike) ends up near zero on real spike events.

POT bypasses the regime question entirely. Per Coles (2001, *Extreme Values*)
and the Pickands–Balkema–de Haan theorem: conditional on exceeding a high
threshold u, the excess Y = X − u | X > u has an approximately generalized
Pareto distribution (GPD) for u high enough. Fitting a GPD to the per-area
right (or left) tail, depending on which side historical price-spikes
actually fall on, gives a clean per-slot tail probability that doesn't
depend on the structure of the *opposite* tail.

Tail direction is chosen automatically per area: we look at the median
residual on slots with realised price > ¥30/kWh (the gate's spike definition).
If that median is positive, spikes are right-tail events; otherwise left.
TK falls out as left-tail (stack model overshoots at peak so realised <
modelled), TH as right-tail (stack model undershoots).

Output
------
For every slot we compute `p_pot_tail` ∈ [0, 1], the empirical-rank tail
probability — 0 means "this residual is on the wrong side of the central
mass for a spike", 1 means "as extreme as anything we've ever seen on
the spike side". Combined with the MRS posterior via `max()` and
renormalised before writing to `regime_states`.

We persist a small set of GPD-fitted parameters so the dashboard / future
diagnostic tools can reproduce the tail curve, but the per-slot probability
itself is computed via empirical-CDF rank on the historical residual
distribution — that is robust at our sample sizes (~46K slots/area) and
doesn't assume a shape parameter ξ that's hard to estimate cleanly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.stats import genpareto  # type: ignore[import-untyped]

logger = logging.getLogger("regime.pot")


_TAIL_QUANTILE = 0.90        # u = 90th percentile of the chosen tail
_DEFAULT_SPIKE_PRICE_KWH = 30.0
_MIN_SPIKE_SLOTS_FOR_DIRECTION = 10
_MIN_TAIL_OBS_FOR_GPD = 50


TailDirection = Literal["right", "left", "both"]


@dataclass
class _POTFit:
    direction: TailDirection
    threshold_u_right: float | None
    threshold_u_left: float | None
    n_tail_obs_right: int
    n_tail_obs_left: int
    gpd_shape_right: float | None
    gpd_scale_right: float | None
    gpd_shape_left: float | None
    gpd_scale_left: float | None
    sorted_residuals: np.ndarray   # full ascending residual series; used for empirical rank


class PeaksOverThreshold:
    """Per-area POT tail estimator.

    Usage::

        pot = PeaksOverThreshold(residuals=r, prices=p)
        pot.fit()
        p_tail = pot.tail_probabilities(r)        # T-vector in [0, 1]
        params = pot.params                        # dict for hyperparams
    """

    def __init__(
        self,
        residuals: np.ndarray,
        prices: np.ndarray,
        *,
        spike_price_threshold_kwh: float = _DEFAULT_SPIKE_PRICE_KWH,
    ):
        if len(residuals) != len(prices):
            raise ValueError(
                f"len(residuals)={len(residuals)} != len(prices)={len(prices)}"
            )
        self.residuals = np.asarray(residuals, dtype=float)
        self.prices = np.asarray(prices, dtype=float)
        self.spike_threshold = float(spike_price_threshold_kwh)
        self._fit: _POTFit | None = None

    # ---------- public --------------------------------------------------

    def fit(self) -> None:
        """Fit GPDs on both tails of the residual distribution.

        Default direction is "both" — TH's high-price slots have a bimodal
        residual mix (some stack-overshoots, some stack-undershoots), and
        per-area direction-pickers can't distinguish them at our sample
        sizes. The fix is to flag any residual that's far from the central
        mass in EITHER direction. Oversupply slots (extreme negative
        residual at low realised price) get filtered out by the gate's
        realised-price filter anyway, so the cost of treating both tails
        as "spike-side" is small.
        """
        direction = self._choose_tail_direction()

        u_right = float(np.percentile(self.residuals, _TAIL_QUANTILE * 100))
        u_left = float(np.percentile(self.residuals, (1 - _TAIL_QUANTILE) * 100))
        right_mask = self.residuals > u_right
        left_mask = self.residuals < u_left
        n_right = int(right_mask.sum())
        n_left = int(left_mask.sum())

        gpd_shape_right = gpd_scale_right = None
        gpd_shape_left = gpd_scale_left = None
        if direction in ("right", "both") and n_right >= _MIN_TAIL_OBS_FOR_GPD:
            try:
                shape, _loc, scale = genpareto.fit(
                    self.residuals[right_mask] - u_right, floc=0
                )
                gpd_shape_right = float(shape)
                gpd_scale_right = float(scale)
            except Exception as e:
                logger.warning("right-tail GPD fit failed: %s", e)
        if direction in ("left", "both") and n_left >= _MIN_TAIL_OBS_FOR_GPD:
            try:
                shape, _loc, scale = genpareto.fit(
                    u_left - self.residuals[left_mask], floc=0
                )
                gpd_shape_left = float(shape)
                gpd_scale_left = float(scale)
            except Exception as e:
                logger.warning("left-tail GPD fit failed: %s", e)

        sorted_residuals = np.sort(self.residuals)

        self._fit = _POTFit(
            direction=direction,
            threshold_u_right=u_right if direction in ("right", "both") else None,
            threshold_u_left=u_left if direction in ("left", "both") else None,
            n_tail_obs_right=n_right,
            n_tail_obs_left=n_left,
            gpd_shape_right=gpd_shape_right,
            gpd_scale_right=gpd_scale_right,
            gpd_shape_left=gpd_shape_left,
            gpd_scale_left=gpd_scale_left,
            sorted_residuals=sorted_residuals,
        )
        logger.info(
            "POT fit: direction=%s u_right=%.3f u_left=%.3f n_right=%d n_left=%d "
            "ξ_right=%s ξ_left=%s",
            direction, u_right, u_left, n_right, n_left,
            f"{gpd_shape_right:.3f}" if gpd_shape_right is not None else "n/a",
            f"{gpd_shape_left:.3f}" if gpd_shape_left is not None else "n/a",
        )

    def tail_probabilities(self, residuals: np.ndarray) -> np.ndarray:
        """Compute per-slot p_pot_tail in [0, 1] for an arbitrary residual vector.

        For each side enabled by ``direction``:
        - rank = empirical CDF of the residual in the historical series
        - p_right = max(0, 2*(rank - 0.5)) — high if residual is in upper tail
        - p_left  = max(0, 2*(0.5 - rank)) — high if residual is in lower tail

        Final p_tail = max of the enabled sides. With direction="both" we
        flag any residual far from the median in either direction; with
        direction="right" or "left" we suppress one side.
        """
        if self._fit is None:
            raise RuntimeError("POT not fitted; call fit() first")
        fit = self._fit
        residuals = np.asarray(residuals, dtype=float)

        ranks = np.searchsorted(fit.sorted_residuals, residuals, side="right")
        cdf = ranks / max(len(fit.sorted_residuals), 1)
        p_right = np.clip(2.0 * (cdf - 0.5), 0.0, 1.0)
        p_left = np.clip(2.0 * (0.5 - cdf), 0.0, 1.0)

        if fit.direction == "right":
            return p_right
        if fit.direction == "left":
            return p_left
        return np.maximum(p_right, p_left)

    @property
    def params(self) -> dict:
        if self._fit is None:
            raise RuntimeError("POT not fitted; call fit() first")
        fit = self._fit
        return {
            "tail_direction": fit.direction,
            "threshold_u_right": fit.threshold_u_right,
            "threshold_u_left": fit.threshold_u_left,
            "tail_quantile": _TAIL_QUANTILE,
            "n_tail_obs_right": fit.n_tail_obs_right,
            "n_tail_obs_left": fit.n_tail_obs_left,
            "gpd_shape_right": fit.gpd_shape_right,
            "gpd_scale_right": fit.gpd_scale_right,
            "gpd_shape_left": fit.gpd_shape_left,
            "gpd_scale_left": fit.gpd_scale_left,
            "spike_price_threshold_kwh": self.spike_threshold,
        }

    # ---------- helpers -------------------------------------------------

    def _choose_tail_direction(self) -> TailDirection:
        """Default to "both" tails — see fit() docstring for the rationale.

        We retain the per-area direction-picker as documentation only: it
        peeks at the residual sign on the top-1% of historical prices and
        logs it for diagnostic purposes, but the returned direction is
        always "both". With direction="both", oversupply tail observations
        don't materially affect the gate (filtered out by realised-price
        threshold), and we capture spike events regardless of whether the
        stack model overshoots or undershoots them.
        """
        cutoff = float(np.percentile(self.prices, 99.0))
        cutoff = max(cutoff, self.spike_threshold)
        spike_mask = self.prices >= cutoff
        n_spikes = int(spike_mask.sum())
        if n_spikes >= _MIN_SPIKE_SLOTS_FOR_DIRECTION:
            median_resid = float(np.median(self.residuals[spike_mask]))
            mean_resid = float(np.mean(self.residuals[spike_mask]))
            logger.info(
                "POT diagnostic: top1%%-cutoff=%.2f n=%d median=%.3f mean=%.3f "
                "(direction=both regardless)",
                cutoff, n_spikes, median_resid, mean_resid,
            )
        return "both"
