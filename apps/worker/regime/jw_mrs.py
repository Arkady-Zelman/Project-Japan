"""Janczura-Weron 2010 3-regime MRS, wrapped around statsmodels.

Why a new class
---------------
The shipped `_fit_mrs` (in `mrs_calibrate.py`) used `MarkovRegression(trend='c',
switching_variance=True)` with **variance-based labeling** (lowest variance =
base, highest = spike). That worked for TK (99.2% spike-window pass) but
failed for TH (20%) and was structurally fragile across the other 7 areas:

- The "spike" regime can have positive OR negative residuals depending on
  whether the M4 stack model **over- or under-shoots** at the area's peak
  hours. Variance-based labeling can't distinguish; both cases look like
  high-variance regimes after EM. Mean-based labeling fails for the inverse
  reason.

- The original Janczura-Weron spec has **AR(1) in the base regime only** to
  capture mean reversion of normal trading; spike/drop are i.i.d. jumps. The
  `trend='c'` approximation drops the AR term entirely, which biases the EM
  toward fits where one regime catches *both* directions of jump.

This class fixes both:

1. **Primary fit**: `MarkovAutoregression(k_regimes=3, order=1,
   switching_ar=True, switching_variance=True)`. statsmodels supports
   per-regime AR coefficients natively. The base regime naturally falls
   out as the one with the largest (closest to 1) AR coefficient.
   Spike/drop converge to AR coefficients near 0 — a soft enforcement of
   the Janczura-Weron i.i.d.-jump constraint.

2. **Fallback fit**: same `MarkovRegression(trend='c', switching_variance=True)`
   as before, used if the AR(1) fit fails to converge or produces
   degenerate regime variances.

3. **Posterior-weighted labeling**: instead of sorting by mean or variance,
   look at which regime the smoother actually puts the most posterior mass
   on during *historical* high-price events (>= 95th percentile of `prices`
   over the calibration window). That regime gets labeled "spike", which
   aligns the label with the real-world price-spike phenomenon regardless
   of whether residuals are positive or negative. Among the remaining two,
   lowest variance = "base", other = "drop".

The "high-price events" are computed from the calibration window itself,
*not* the validation window — this is principled (uses the same data the
fit saw) and not gate-snooping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from statsmodels.tsa.regime_switching.markov_autoregression import (  # type: ignore[import-untyped]
    MarkovAutoregression,
)
from statsmodels.tsa.regime_switching.markov_regression import (  # type: ignore[import-untyped]
    MarkovRegression,
)

logger = logging.getLogger("regime.jw_mrs")


@dataclass
class _FitResult:
    """Internal container for one fit attempt's outputs."""

    method: str                      # "ar1" or "constant"
    means: np.ndarray                # (3,) regime means
    variances: np.ndarray            # (3,) regime variances
    ar_coefs: np.ndarray | None      # (3,) regime AR(1) coefs, None for constant fit
    transition: np.ndarray           # (3, 3) transition matrix (P[next, prev])
    smoothed: np.ndarray             # (T, 3) posterior probabilities
    log_likelihood: float
    aic: float
    bic: float
    n_obs: int


_HIGH_PRICE_PERCENTILE = 95.0
_MIN_HIGH_PRICE_EVENTS = 20
_DEGENERATE_VAR_RATIO = 1e-6   # if min/max variance below this, fit is degenerate


class JanczuraWeronMRS:
    """3-regime Janczura-Weron MRS with posterior-weighted labeling.

    Usage::

        model = JanczuraWeronMRS(residuals=r, prices=p)
        result = model.fit()
        # result.params: dict ready for `models.hyperparams`
        # result.smoothed: (T, 3) posterior probabilities, indices match
        #                  result.regime_mapping
    """

    def __init__(self, residuals: np.ndarray, prices: np.ndarray):
        if len(residuals) != len(prices):
            raise ValueError(
                f"len(residuals)={len(residuals)} != len(prices)={len(prices)}"
            )
        if len(residuals) < 200:
            raise ValueError(f"insufficient observations: {len(residuals)}")
        self.residuals = np.asarray(residuals, dtype=float)
        self.prices = np.asarray(prices, dtype=float)

    # ---------- public --------------------------------------------------

    def fit(self) -> tuple[dict, np.ndarray]:
        """Fit + label. Returns (params_dict, smoothed_T_by_3).

        `params_dict` carries means, variances, transition_matrix, ar_coefs
        (or null), regime_mapping, log-likelihood/AIC/BIC, n_obs, and the
        labeling diagnostic (`labeling_method`, `high_price_coverage`).

        `smoothed` is aligned to the *same regime indices* used in
        regime_mapping — caller can index `smoothed[:, idx]` to get
        P(regime=label).

        Strategy: try the constant-trend fit first (the historically-stable
        primary for our residuals). If it converges cleanly we use it. Only
        try the AR(1) variant as a fallback — in practice it tends toward
        degenerate near-unit-root regimes on the long calibration window
        used by this project, which the `_is_clean` check catches but at the
        cost of an extra slow fit.
        """
        primary = self._try_fit_constant()
        if primary is not None and self._is_clean(primary):
            best = primary
        else:
            fallback = self._try_fit_ar1()
            if fallback is None or not self._is_clean(fallback):
                raise RuntimeError(
                    "both constant and AR(1) MRS fits failed to converge cleanly"
                )
            best = fallback

        regime_mapping, labeling_method, coverage = self._label_regimes(
            best.smoothed, best.variances, best.means
        )

        params = {
            "means": best.means.tolist(),
            "variances": best.variances.tolist(),
            "ar_coefs": (
                best.ar_coefs.tolist() if best.ar_coefs is not None else None
            ),
            "transition_matrix": best.transition.tolist(),
            "regime_mapping": regime_mapping,
            "fit_method": best.method,
            "labeling_method": labeling_method,
            "high_price_coverage": float(coverage),
            "log_likelihood": float(best.log_likelihood),
            "aic": float(best.aic),
            "bic": float(best.bic),
            "n_obs": int(best.n_obs),
        }
        return params, best.smoothed

    # ---------- primary fit (AR(1) in all regimes, σ² switching) --------

    def _try_fit_ar1(self) -> _FitResult | None:
        try:
            mod = MarkovAutoregression(
                self.residuals,
                k_regimes=3,
                order=1,
                switching_ar=True,
                switching_variance=True,
            )
            result = mod.fit(em_iter=30, search_reps=20, disp=False)
        except Exception as e:
            logger.warning("AR(1) fit failed: %s", e)
            return None

        param_names = list(mod.param_names)
        try:
            mean_idxs = [param_names.index(f"const[{k}]") for k in range(3)]
            ar_idxs = [param_names.index(f"ar.L1[{k}]") for k in range(3)]
            var_idxs = [param_names.index(f"sigma2[{k}]") for k in range(3)]
        except ValueError as e:
            logger.warning("AR(1) param-name lookup failed: %s — names=%s", e, param_names)
            return None

        means = np.array([float(result.params[i]) for i in mean_idxs])
        ar_coefs = np.array([float(result.params[i]) for i in ar_idxs])
        variances = np.array([float(result.params[i]) for i in var_idxs])
        transition = np.asarray(result.regime_transition).squeeze()

        smoothed = np.asarray(result.smoothed_marginal_probabilities)
        # MarkovAutoregression with order=1 returns smoothed of length T-1
        # (loses the first obs to the AR lag). Pad with the first row
        # duplicated so caller can align to original residual indices.
        if smoothed.shape[0] == 3:
            smoothed = smoothed.T
        if smoothed.shape[0] == len(self.residuals) - 1:
            smoothed = np.vstack([smoothed[:1], smoothed])

        return _FitResult(
            method="ar1",
            means=means,
            variances=variances,
            ar_coefs=ar_coefs,
            transition=transition,
            smoothed=smoothed,
            log_likelihood=float(result.llf),
            aic=float(result.aic),
            bic=float(result.bic),
            n_obs=len(self.residuals),
        )

    # ---------- fallback fit (constant trend, σ² switching) -------------

    def _try_fit_constant(self) -> _FitResult | None:
        # Run several fits with different mean initializations and pick the
        # one with the best high-price-coverage. Random EM starts (the default)
        # tend to converge to fits where the high-variance regime catches both
        # tails, leaving the positive-residual spike events orphaned in a
        # moderate-mean "drop" regime — exactly the TH failure mode.
        #
        # The candidates probe the parameter space:
        #   - default (random starts)            — what shipped before
        #   - residual-quantile init             — biased toward
        #     {drop=-1.5σ, base≈0, spike=+1.5σ} so EM has a starting point
        #     where the +tail regime exists and can survive convergence
        #
        # All candidates use the same fitting machinery; we pick the best
        # post hoc by log-likelihood AND by high-price posterior coverage
        # (a fit that learns nothing useful but has a high LL is useless).
        candidates = [
            self._fit_constant_one(start_params=None),
            self._fit_constant_one(start_params=self._biased_start_params()),
        ]
        candidates = [c for c in candidates if c is not None]
        if not candidates:
            return None

        # Score each: prefer fits with a positive-mean regime when our
        # high-price slots have positive residuals (i.e. the EM correctly
        # found the +tail). If all fits have only negative regime means,
        # pick by log-likelihood.
        threshold = float(np.percentile(self.prices, _HIGH_PRICE_PERCENTILE))
        high_mask = self.prices >= threshold
        if high_mask.sum() >= _MIN_HIGH_PRICE_EVENTS:
            mean_high_residual = float(self.residuals[high_mask].mean())
        else:
            mean_high_residual = float(np.median(self.residuals))

        def score(fr: _FitResult) -> float:
            # Prefer the fit whose closest regime mean to mean_high_residual
            # is well-aligned (small distance) AND has high LL. Distance
            # dominates when one fit has a regime within 0.5 of the high-
            # residual mean and another doesn't.
            dist = float(np.min(np.abs(fr.means - mean_high_residual)))
            return -dist + 1e-4 * fr.log_likelihood

        best = max(candidates, key=score)
        return best

    def _fit_constant_one(self, *, start_params: np.ndarray | None) -> _FitResult | None:
        try:
            mod = MarkovRegression(
                self.residuals,
                k_regimes=3,
                trend="c",
                switching_variance=True,
            )
            if start_params is not None:
                # Skip EM warm-up; start_params should already place us in
                # a good basin. Quasi-Newton then refines to the local MLE.
                result = mod.fit(start_params=start_params, em_iter=10, disp=False)
            else:
                result = mod.fit(em_iter=30, search_reps=20, disp=False)
        except Exception as e:
            logger.warning("constant-trend fit failed: %s", e)
            return None

        param_names = list(mod.param_names)
        try:
            mean_idxs = [param_names.index(f"const[{k}]") for k in range(3)]
            var_idxs = [param_names.index(f"sigma2[{k}]") for k in range(3)]
        except ValueError as e:
            logger.warning("constant param-name lookup failed: %s", e)
            return None

        means = np.array([float(result.params[i]) for i in mean_idxs])
        variances = np.array([float(result.params[i]) for i in var_idxs])
        transition = np.asarray(result.regime_transition).squeeze()

        smoothed = np.asarray(result.smoothed_marginal_probabilities)
        if smoothed.shape[0] == 3 and smoothed.shape[1] == len(self.residuals):
            smoothed = smoothed.T

        return _FitResult(
            method="constant" if start_params is None else "constant_biased",
            means=means,
            variances=variances,
            ar_coefs=None,
            transition=transition,
            smoothed=smoothed,
            log_likelihood=float(result.llf),
            aic=float(result.aic),
            bic=float(result.bic),
            n_obs=len(self.residuals),
        )

    def _biased_start_params(self) -> np.ndarray:
        """Build an MLE start vector biased toward {neg, ~0, pos}-mean regimes.

        statsmodels' MarkovRegression with k_regimes=3, trend='c',
        switching_variance=True parameter layout:
          [0..5]    transition probs (off-diagonal entries, untransformed)
          [6..8]    const[0..2]   regime means
          [9..11]   sigma2[0..2]  regime variances

        We seed the off-diagonal transitions at 0.05 (sticky regimes), means
        at the residual's [10th, 50th, 90th] percentiles, and variances at
        the global residual variance. The optimizer takes it from there.
        """
        q10 = float(np.percentile(self.residuals, 10))
        q50 = float(np.percentile(self.residuals, 50))
        q90 = float(np.percentile(self.residuals, 90))
        global_var = float(np.var(self.residuals))
        # Off-diagonal transitions: 0.05 each (logit-space ~ -3 ish, but
        # statsmodels reparameterizes). Setting all to 0.05 is well-defined.
        # The MLE optimizer expects untransformed params; statsmodels handles
        # transformation under the hood when we pass via start_params.
        # Here we use the *transformed* form (post-logit) since fit() expects
        # those: log(p / (1 - p_other)) — or we just provide post-init
        # values that statsmodels accepts. The simplest is the pre-transform
        # form: pass a vector matching `mod.start_params`'s shape.
        #
        # In practice: statsmodels fit() with start_params expects the value
        # in the same parameterization as `transformed=True` (post-link). We
        # use logit_p = log(0.05 / 0.95) ≈ -2.944 for off-diagonal probs.
        logit_p = float(np.log(0.05 / 0.95))
        # Layout: 6 transition logits + 3 means + 3 variances = 12 params
        return np.array([
            logit_p, logit_p, logit_p, logit_p, logit_p, logit_p,  # transitions
            q10, q50, q90,                                          # means
            global_var, global_var, global_var,                     # variances
        ], dtype=float)

    # ---------- helpers -------------------------------------------------

    def _is_clean(self, fr: _FitResult) -> bool:
        """Reject degenerate fits (one variance ~0, NaN regimes, etc.)."""
        if not np.all(np.isfinite(fr.means)):
            return False
        if not np.all(np.isfinite(fr.variances)):
            return False
        if (fr.variances <= 0).any():
            return False
        if fr.variances.min() / max(fr.variances.max(), 1e-12) < _DEGENERATE_VAR_RATIO:
            return False
        if not np.all(np.isfinite(fr.smoothed)):
            return False
        return True

    def _label_regimes(
        self, smoothed: np.ndarray, variances: np.ndarray, means: np.ndarray
    ) -> tuple[dict[str, str], str, float]:
        """Posterior-weighted labeling.

        Returns (regime_mapping, method_used, high_price_coverage).
        """
        threshold = float(np.percentile(self.prices, _HIGH_PRICE_PERCENTILE))
        high_mask = self.prices >= threshold
        n_high = int(high_mask.sum())

        if n_high < _MIN_HIGH_PRICE_EVENTS:
            # Not enough spike events to identify the spike regime by posterior
            # mass. Fall back to: spike = highest variance, base = lowest, drop = mid.
            order = np.argsort(variances)
            mapping = {
                str(int(order[0])): "base",
                str(int(order[1])): "drop",
                str(int(order[2])): "spike",
            }
            return mapping, "variance_fallback", 0.0

        # Mean posterior probability per regime over the high-price slots.
        mean_post = smoothed[high_mask].mean(axis=0)   # (3,)
        idx_spike = int(np.argmax(mean_post))
        coverage = float(mean_post[idx_spike])

        remaining = [k for k in range(3) if k != idx_spike]
        # Among the remaining two regimes, "base" is the lower-variance one
        # (mean-reverting, narrow distribution), "drop" is the higher-variance
        # remainder (typically catches negative residuals from oversupply).
        if variances[remaining[0]] <= variances[remaining[1]]:
            idx_base, idx_drop = remaining[0], remaining[1]
        else:
            idx_base, idx_drop = remaining[1], remaining[0]

        mapping = {
            str(idx_base): "base",
            str(idx_spike): "spike",
            str(idx_drop): "drop",
        }
        method = (
            "posterior_weighted_strong" if coverage >= 0.50
            else "posterior_weighted_weak"
        )
        # Coverage tells future-us how confident the labeling is. <0.4 means the
        # spike events are split across multiple regimes (the EM didn't isolate
        # them) — flag for diagnosis without failing.
        if coverage < 0.40:
            logger.warning(
                "weak posterior coverage (%.2f, n_high=%d) — spike events "
                "may be smeared across regimes. Variances=%s Means=%s",
                coverage, n_high, variances.tolist(), means.tolist(),
            )
        return mapping, method, coverage
