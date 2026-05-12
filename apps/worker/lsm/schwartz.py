"""Schwartz 1-factor mean-reverting price simulator.

Used by the Boogert-de Jong gate test (BUILD_SPEC §8.5 setup). Could be
reused later if production grows beyond 48-slot horizons and we need a
synthetic extrapolator.

Process:
    d(log S) = κ(μ − log S) dt + σ dW

With μ = log(S₀), discretized via the standard log-normal Euler step:
    log S_{t+1} = log S_t + κ(μ − log S_t) Δt + σ √Δt · ε,  ε ~ N(0, 1)

**Convention**: σ and κ are passed as **per-step** parameters (with the
step-size implicit in `dt_days`). For the spec's gate test (σ=0.0945,
κ=0.05, dt_days=1) this gives a long-run log-price stdev of √(σ²/(2κ)) ≈
0.30, i.e. price varies ±30% around S₀. This matches the spec's intended
"high volatility" regime that produces the 5,502,115 EUR target.
"""

from __future__ import annotations

import numpy as np


def simulate_schwartz_paths(
    n_paths: int,
    sigma: float,
    kappa: float,
    T_days: int,
    S0: float,
    *,
    dt_days: float = 1.0,
    seed: int | None = None,
    antithetic: bool = False,
) -> np.ndarray:
    """Simulate `n_paths` Schwartz 1-factor paths over `T_days` calendar days.

    `sigma` and `kappa` are **per-step** (compatible with BUILD_SPEC §8.5).

    Returns array of shape `(n_paths, n_steps + 1)` where
    `n_steps = int(T_days / dt_days)`.

    Each row begins at `S0` and evolves under the Schwartz mean-reverting
    log-process. Setting `seed` fixes the RNG for reproducibility (the gate
    test uses seed=42).

    Antithetic-variates mode (M10C L3) pairs each base path with its
    sign-flipped twin to halve variance for free. `n_paths` must be even
    when `antithetic=True`.
    """
    rng = np.random.default_rng(seed)
    n_steps = int(round(T_days / dt_days))

    log_mu = np.log(S0)
    log_S = np.full((n_paths, n_steps + 1), log_mu, dtype=np.float64)
    sqrt_dt = np.sqrt(dt_days)

    if antithetic:
        if n_paths % 2 != 0:
            raise ValueError("antithetic mode requires even n_paths")
        half = n_paths // 2

    for t in range(n_steps):
        if antithetic:
            eps_half = rng.standard_normal(half)
            eps = np.concatenate([eps_half, -eps_half])
        else:
            eps = rng.standard_normal(n_paths)
        log_S[:, t + 1] = (
            log_S[:, t]
            + kappa * (log_mu - log_S[:, t]) * dt_days
            + sigma * sqrt_dt * eps
        )

    return np.exp(log_S)
