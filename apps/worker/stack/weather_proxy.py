"""Solar/wind output estimator for slots where `generation_mix_actuals` is missing.

The stack engine subtracts variable-renewable output from area demand before
clearing the merit-order curve. Where `generation_mix_actuals` has a row, we
use the metered output. Where it doesn't (CB/KS/CG/KY post-2024-04, or any
slot the upstream hasn't published yet), we estimate from `weather_obs`:

    solar_mw = installed_pv_mw * (GHI / 1000) * pv_derate
    wind_mw  = installed_wind_mw * power_curve(wind_mps)

Both formulas are first-order approximations — adequate for stack-model
capacity reduction; not adequate for VRE forecasting. The stack engine
TAGS slots as "estimated" when this fallback fires so the dashboard
can flag them clearly to the operator.

Installed capacities are nameplate FIT-supported PV/wind by area, drawn
from METI ENECHO 再生可能エネルギー固定価格買取制度 statistics
(~2024 update). They drift up over time as new capacity is commissioned;
refresh annually.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Per-area installed renewable capacity (MW). Approximate, METI 2024.
# ---------------------------------------------------------------------------

# Each row: area_code → (installed_pv_mw, installed_wind_mw).
# These values include FIT-supported utility-scale + distributed PV.
# Source: METI ENECHO renewable statistics, consolidated 2024-Q4 figures.
INSTALLED_CAPACITY_BY_AREA: dict[str, tuple[float, float]] = {
    "HK": (2300.0, 700.0),
    "TH": (8500.0, 1900.0),
    "TK": (12000.0, 600.0),
    "CB": (8000.0, 200.0),
    "HR": (1000.0, 200.0),
    "KS": (6000.0, 100.0),
    "CG": (3500.0, 400.0),
    "SK": (2200.0, 200.0),
    "KY": (9500.0, 700.0),
}


# Solar derate factor — accounts for BoS losses, soiling, inverter
# efficiency, and temperature coefficient at typical operating conditions.
# IEA/IRENA composite default for Japanese installations.
_PV_DERATE: float = 0.83


# ---------------------------------------------------------------------------
# IEC 61400-1 Class II onshore wind turbine power curve (normalized 0..1)
# ---------------------------------------------------------------------------
#
# Approximation tuned to the average Japanese onshore wind fleet.
#   cut-in:   3 m/s
#   rated:    12 m/s
#   cut-out:  25 m/s


_WIND_CUT_IN_MPS: float = 3.0
_WIND_RATED_MPS: float = 12.0
_WIND_CUT_OUT_MPS: float = 25.0


def wind_capacity_factor(wind_mps: float) -> float:
    """Normalized wind output (0..1) for a given wind speed at hub height.

    Cubic ramp between cut-in and rated, flat at rated power until cut-out,
    zero above cut-out. Reasonable proxy for fleet-average behaviour.
    """
    if wind_mps < _WIND_CUT_IN_MPS or wind_mps >= _WIND_CUT_OUT_MPS:
        return 0.0
    if wind_mps >= _WIND_RATED_MPS:
        return 1.0
    # Cubic ramp from cut-in to rated.
    span = _WIND_RATED_MPS - _WIND_CUT_IN_MPS
    fraction = (wind_mps - _WIND_CUT_IN_MPS) / span
    return min(1.0, max(0.0, fraction**3))


# ---------------------------------------------------------------------------
# Public API — used by stack/build_curve.py
# ---------------------------------------------------------------------------


def solar_proxy_mw(area_code: str, ghi_w_m2: float | None) -> float:
    """Estimate solar output for an area at one slot from GHI."""
    if ghi_w_m2 is None or ghi_w_m2 <= 0:
        return 0.0
    pv_mw, _ = INSTALLED_CAPACITY_BY_AREA.get(area_code, (0.0, 0.0))
    return pv_mw * (ghi_w_m2 / 1000.0) * _PV_DERATE


def wind_proxy_mw(area_code: str, wind_mps: float | None) -> float:
    """Estimate wind output for an area at one slot from hub-height wind speed."""
    if wind_mps is None:
        return 0.0
    _, wind_mw = INSTALLED_CAPACITY_BY_AREA.get(area_code, (0.0, 0.0))
    return wind_mw * wind_capacity_factor(wind_mps)
