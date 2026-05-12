"""Boogert & de Jong (2006) Least-Squares Monte Carlo for storage valuation.

Algorithm (BUILD_SPEC §8.1):

For each path b in 1..M, simulate prices S^b(1..T+1) [supplied externally]
For each volume grid point n in 1..N: initialise Y(T+1, n) = 0

For t = T-1 down to 0:
    For each volume grid point n:
        Fit OLS: Y(t+1, n) ≈ Σ_q β_q · φ_q(S(t))   over paths
        Save β[t, n, :]

    For each path b, each volume grid point n:
        Determine action Δv* maximising:
            h(S^b(t), Δv) + e^{-δ·dt} · Σ_q β[t, n_target, q] · φ_q(S^b(t))
        subject to:
            v_grid[n] + Δv ∈ [v_min, v_max]
            Δv ∈ [-max_discharge_step, +max_charge_step]
        Y[b, n] := value at optimum

Forward sweep (one per path, starting from soc_initial):
    For t = 0..T-1:
        Use β[t] to find Δv* given current v.
        Apply: v += Δv*; accumulate discounted cash.
    accumulated[b] := total cash

Total = mean(accumulated); intrinsic = same algorithm on the path-mean
deterministic price series; extrinsic = total − intrinsic. CI bounds =
5/95 percentiles of accumulated[b].

Implementation:
- Backward sweep is `@numba.njit(parallel=True)` with `numba.prange` over
  the volume grid index for the OLS fit and over paths × grid for the
  inner action loop. ~30K iterations of OLS on (M=1000, K=4) per t, plus
  M·N action evaluations — all parallelizable.
- Forward sweep is `@numba.njit(parallel=True)` with prange over paths.
- Action discretisation: candidate post-action volumes restricted to grid
  points so continuation lookup is exact (no interpolation needed). Action
  granularity = grid spacing. For N=101 and the paper's setup this is
  2,500 MWh per step which exactly matches the paper's i_max constraint;
  for the BESS production case (N=101, energy=400 MWh, soc range 40-380)
  spacing ≈ 3.4 MWh which is well below the 50 MWh half-hour rate cap.
"""

from __future__ import annotations

import logging
import time

import numpy as np
from numba import njit, prange  # type: ignore[import-untyped]

from .models import AssetSpec, ValuationResult

logger = logging.getLogger("lsm.engine")

DEFAULT_N_VOLUME_GRID = 101
DEFAULT_N_BASIS = 6   # power basis: 1, S, S², S³, S⁴, S⁵


# ---------------------------------------------------------------------------
# Numba kernels
# ---------------------------------------------------------------------------


@njit(cache=False, fastmath=False)
def _basis_eval(S: float, scale: float, n_basis: int) -> np.ndarray:
    """Polynomial basis [1, z, z², z³, ...] where z = S / scale.

    `scale` is a per-timestep normalisation (typically the cross-path RMS
    of prices at that t). Using normalised price avoids the (X^T X)
    condition number blowing up at z³ for S~15 EUR (where without scaling,
    S³ ≈ 3375 vs S ≈ 15 means the polynomial columns are scaled by 200×).
    """
    z = S / scale
    out = np.empty(n_basis, dtype=np.float64)
    out[0] = 1.0
    if n_basis >= 2:
        out[1] = z
    if n_basis >= 3:
        out[2] = z * z
    if n_basis >= 4:
        out[3] = z * z * z
    if n_basis >= 5:
        out[4] = z * z * z * z
    if n_basis >= 6:
        out[5] = z * z * z * z * z
    return out


@njit(cache=False, fastmath=False)
def _build_X(prices_t: np.ndarray, scale: float, n_basis: int) -> np.ndarray:
    """Build the design matrix X of shape (M, K) for OLS at one timestep."""
    M = prices_t.shape[0]
    X = np.empty((M, n_basis), dtype=np.float64)
    for i in range(M):
        z = prices_t[i] / scale
        X[i, 0] = 1.0
        if n_basis >= 2:
            X[i, 1] = z
        if n_basis >= 3:
            X[i, 2] = z * z
        if n_basis >= 4:
            X[i, 3] = z * z * z
        if n_basis >= 5:
            X[i, 4] = z * z * z * z
        if n_basis >= 6:
            X[i, 5] = z * z * z * z * z
    return X


@njit(cache=False, fastmath=False)
def _rms(x: np.ndarray) -> float:
    """Cross-path RMS of one timestep of prices, for basis normalisation."""
    s = 0.0
    for i in range(x.shape[0]):
        s += x[i] * x[i]
    return np.sqrt(s / x.shape[0])


@njit(cache=False, fastmath=False)
def _ols_solve(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """OLS via numpy.linalg.lstsq (SVD-based pseudoinverse).

    Numba supports `np.linalg.lstsq` since 0.55. SVD is more stable than
    the normal-equations form (β = (X^T X)^-1 X^T y) — for the polynomial
    basis on prices ranging S ∈ [10, 20] EUR, the condition number of
    (X^T X) hits ~1e7 even with the basis already scaled to unit RMS.
    SVD's effective tolerance handles near-singular columns correctly.
    """
    beta, _, _, _ = np.linalg.lstsq(X, y)
    return beta


@njit(parallel=True, cache=False, fastmath=False)
def _backward_sweep(
    prices: np.ndarray,                   # (M, T+1)
    volume_grid: np.ndarray,              # (N,)
    max_charge_step: float,
    max_discharge_step: float,
    sqrt_eff: float,
    degradation: float,
    discount_per_step: float,
    n_basis: int,
) -> tuple:
    """Returns (betas, scales): coefficients (T, N, K) + per-t basis scales (T,)."""
    M = prices.shape[0]
    T = prices.shape[1] - 1
    N = volume_grid.shape[0]

    Y = np.zeros((M, N), dtype=np.float64)
    betas = np.zeros((T, N, n_basis), dtype=np.float64)
    scales = np.ones(T, dtype=np.float64)

    for t in range(T - 1, -1, -1):
        S_t = prices[:, t]
        scale_t = _rms(S_t)
        if scale_t <= 0.0:
            scale_t = 1.0
        scales[t] = scale_t
        X = _build_X(S_t, scale_t, n_basis)

        # ---- OLS regression per volume grid point (parallel over n) ----
        for n in prange(N):
            beta = _ols_solve(X, Y[:, n])
            for q in range(n_basis):
                betas[t, n, q] = beta[q]

        # ---- Optimal-action update per (path, grid point) ---------------
        Y_new = np.empty((M, N), dtype=np.float64)
        for b in prange(M):
            S = S_t[b]
            phi = _basis_eval(S, scale_t, n_basis)
            for n in range(N):
                v = volume_grid[n]
                best_val = -1e18
                # Enumerate candidate post-action grid points.
                for n_target in range(N):
                    new_v = volume_grid[n_target]
                    delta_v = new_v - v
                    if delta_v > max_charge_step + 1e-9:
                        continue
                    if -delta_v > max_discharge_step + 1e-9:
                        continue
                    # Cash flow (sign convention: charge = cost, discharge = revenue).
                    if delta_v >= 0:
                        h = -delta_v * S / sqrt_eff - delta_v * degradation
                    else:
                        h = -delta_v * S * sqrt_eff + delta_v * degradation
                    # Continuation at exact grid point n_target (no interpolation needed).
                    cont = 0.0
                    for q in range(n_basis):
                        cont += betas[t, n_target, q] * phi[q]
                    val = h + discount_per_step * cont
                    if val > best_val:
                        best_val = val
                Y_new[b, n] = best_val

        # Copy Y_new into Y for the next iteration.
        for b in range(M):
            for n in range(N):
                Y[b, n] = Y_new[b, n]

    return betas, scales


@njit(parallel=True, cache=False, fastmath=False)
def _forward_sweep(
    prices: np.ndarray,                   # (M, T+1)
    betas: np.ndarray,                    # (T, N, K)
    scales: np.ndarray,                   # (T,)
    volume_grid: np.ndarray,              # (N,)
    soc_initial: float,
    max_charge_step: float,
    max_discharge_step: float,
    sqrt_eff: float,
    degradation: float,
    discount_per_step: float,
    n_basis: int,
) -> tuple:
    """Forward sweep: per path, follow optimal actions and accumulate cash.

    Returns (soc_paths (M, T+1), action_paths (M, T), accumulated (M,)).
    """
    M = prices.shape[0]
    T = prices.shape[1] - 1
    N = volume_grid.shape[0]

    soc_paths = np.empty((M, T + 1), dtype=np.float64)
    action_paths = np.empty((M, T), dtype=np.float64)
    accumulated = np.empty(M, dtype=np.float64)

    for b in prange(M):
        v = soc_initial
        cash = 0.0
        df = 1.0
        soc_paths[b, 0] = v
        for t in range(T):
            S = prices[b, t]
            phi = _basis_eval(S, scales[t], n_basis)

            # Find the post-action grid point that maximises immediate + continuation.
            best_val = -1e18
            best_delta = 0.0
            for n_target in range(N):
                new_v = volume_grid[n_target]
                delta_v = new_v - v
                if delta_v > max_charge_step + 1e-9:
                    continue
                if -delta_v > max_discharge_step + 1e-9:
                    continue
                # Cash flow.
                if delta_v >= 0:
                    h = -delta_v * S / sqrt_eff - delta_v * degradation
                else:
                    h = -delta_v * S * sqrt_eff + delta_v * degradation
                cont = 0.0
                for q in range(n_basis):
                    cont += betas[t, n_target, q] * phi[q]
                val = h + discount_per_step * cont
                if val > best_val:
                    best_val = val
                    best_delta = delta_v

            # Apply optimal action.
            v += best_delta
            # Realised cash (immediate, discounted to t=0).
            if best_delta >= 0:
                h_realised = -best_delta * S / sqrt_eff - best_delta * degradation
            else:
                h_realised = -best_delta * S * sqrt_eff + best_delta * degradation
            cash += df * h_realised
            df *= discount_per_step

            soc_paths[b, t + 1] = v
            action_paths[b, t] = best_delta

        accumulated[b] = cash

    return soc_paths, action_paths, accumulated


# ---------------------------------------------------------------------------
# Pure-Python wrapper
# ---------------------------------------------------------------------------


def run_lsm(
    paths: np.ndarray,
    asset: AssetSpec,
    *,
    n_volume_grid: int = DEFAULT_N_VOLUME_GRID,
    basis: str = "power",
    dt_days: float = 1.0,
    discount_rate: float = 0.0,
    oos_paths: np.ndarray | None = None,
) -> ValuationResult:
    """Boogert-de Jong LSM valuation.

    Args:
      paths: (M, T+1) ndarray of prices in JPY/MWh (or EUR/MWh for the
        gate test). Used for backward β fit. Currency must match
        `degradation_jpy_mwh`.
      asset: AssetSpec.
      n_volume_grid: number of volume grid points. 101 ≈ paper default;
        51 is twice as fast with <0.5% deviation.
      basis: "power" (1, S, S², S³) only for v1. `bspline` is parked as
        M10C L3 lever 2 (Carriere-Longstaff B-splines).
      dt_days: timestep length in days. 1.0 for paper, 1/48 for half-hour.
      discount_rate: continuous-compound discount rate δ; annual.
      oos_paths: optional (M', T+1) ndarray. When provided, the backward
        sweep fits β on `paths` while the forward sweep dispatches on
        `oos_paths`. Eliminates in-sample bias (M10C L3 lever 1).

    Returns ValuationResult with all the headline numbers + per-slot
    summaries suitable for `valuation_decisions`.
    """
    if basis != "power":
        raise NotImplementedError(f"basis='{basis}' not yet supported; v1 ships 'power'")

    paths = np.ascontiguousarray(paths, dtype=np.float64)
    M, T_plus_1 = paths.shape
    T = T_plus_1 - 1

    # Volume grid covers [soc_min_mwh, soc_max_mwh].
    volume_grid = np.linspace(
        asset.soc_min_mwh, asset.soc_max_mwh, n_volume_grid, dtype=np.float64,
    )

    # Per-step rate caps in MWh/step.
    hours_per_step = 24.0 * dt_days
    max_charge_step = asset.power_mw_charge * hours_per_step
    max_discharge_step = asset.power_mw_discharge * hours_per_step

    sqrt_eff = float(np.sqrt(asset.round_trip_eff))
    degradation = asset.degradation_jpy_mwh
    # Discount factor per timestep: e^{-δ * dt_years}.
    discount_per_step = float(np.exp(-discount_rate * dt_days / 365.0))

    n_basis = DEFAULT_N_BASIS

    t0 = time.time()
    logger.info(
        "LSM start: M=%d T=%d N=%d basis=%s dt_days=%.4f", M, T, n_volume_grid, basis, dt_days,
    )
    betas, scales = _backward_sweep(
        paths, volume_grid,
        max_charge_step, max_discharge_step, sqrt_eff, degradation,
        discount_per_step, n_basis,
    )
    forward_paths = (
        paths
        if oos_paths is None
        else np.ascontiguousarray(oos_paths, dtype=np.float64)
    )
    soc_paths, action_paths, accumulated = _forward_sweep(
        forward_paths, betas, scales, volume_grid,
        asset.soc_initial_mwh,
        max_charge_step, max_discharge_step, sqrt_eff, degradation,
        discount_per_step, n_basis,
    )

    total = float(np.mean(accumulated))
    ci_lo = float(np.percentile(accumulated, 5))
    ci_hi = float(np.percentile(accumulated, 95))

    # Intrinsic value = same algorithm on the path-mean (deterministic) series.
    mean_path = paths.mean(axis=0).reshape(1, T_plus_1)
    intr_betas, intr_scales = _backward_sweep(
        mean_path, volume_grid,
        max_charge_step, max_discharge_step, sqrt_eff, degradation,
        discount_per_step, n_basis,
    )
    _, _, intr_accum = _forward_sweep(
        mean_path, intr_betas, intr_scales, volume_grid,
        asset.soc_initial_mwh,
        max_charge_step, max_discharge_step, sqrt_eff, degradation,
        discount_per_step, n_basis,
    )
    intrinsic = float(intr_accum[0])
    extrinsic = total - intrinsic

    # Per-slot summaries.
    slot_mean_soc = soc_paths.mean(axis=0).tolist()
    slot_mean_action_mw = (action_paths.mean(axis=0) / hours_per_step).tolist()
    # Expected p&l per slot = mean cash flow.
    slot_pnl = []
    for t in range(T):
        Δ = action_paths[:, t]
        S = paths[:, t]
        h = np.where(
            Δ >= 0,
            -Δ * S / sqrt_eff - Δ * degradation,
            -Δ * S * sqrt_eff + Δ * degradation,
        )
        slot_pnl.append(float(h.mean()))

    runtime = time.time() - t0
    logger.info(
        "LSM done: total=%.2f intrinsic=%.2f extrinsic=%.2f CI=[%.2f, %.2f] in %.2fs",
        total, intrinsic, extrinsic, ci_lo, ci_hi, runtime,
    )

    return ValuationResult(
        total_jpy=total, intrinsic_jpy=intrinsic, extrinsic_jpy=extrinsic,
        ci_lower_jpy=ci_lo, ci_upper_jpy=ci_hi,
        n_paths=M, n_volume_grid=n_volume_grid,
        runtime_seconds=runtime,
        slot_mean_soc_mwh=slot_mean_soc,
        slot_mean_action_mw=slot_mean_action_mw,
        slot_expected_pnl_jpy=slot_pnl,
    )
