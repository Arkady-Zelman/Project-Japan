"""Short-run marginal cost (SRMC) formula + fuel-price unit conversions.

Per BUILD_SPEC §7.3 step 2:

    SRMC_jpy_mwh = (fuel_price_jpy_mwh / efficiency)
                   + variable_om_jpy_mwh
                   + co2_intensity * carbon_price_jpy_t

Renewables and pumped storage return ~0. Nuclear has a fuel-cycle constant
since uranium prices barely move at our resolution and we don't ingest them.

Carbon price: hardcoded to 0 in v1 — Japan's GX-ETS Phase 2 (mandatory) doesn't
start until 2026-2027 and there's no compliance carbon market across the
backfill window. If a real carbon price activates later, lift this constant
into a `carbon_prices` table or env var without touching call sites.
"""

from __future__ import annotations

from .models import Generator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Japan has no mandatory compliance carbon market in the v1 backfill window
# (2023-01 → 2026-04). GX-ETS Phase 1 is voluntary; Phase 2 mandatory pricing
# is scheduled for 2026 onwards. Set non-zero when a real price clears.
CARBON_PRICE_JPY_T: float = 0.0


# Nuclear fuel-cycle cost — not in `fuel_prices` (which carries fossil
# benchmarks). Approximate value from JAERI / IEA "Projected Costs of
# Generating Electricity 2020" — Japan-specific nuclear is ~¥1.4/kWh
# fuel-cycle, ~¥1400/MWh. Bundled into variable_om in the seed YAML, so
# this is here only for clarity and future migration if a uranium feed
# is added. SRMC for nuclear uses variable_om_jpy_mwh as the dominant cost.
NUCLEAR_FUEL_CYCLE_JPY_MWH: float = 0.0  # already counted in variable_om_jpy_mwh


# Heat-content conversions — public-domain figures used industry-wide.
# MMBtu = million British thermal units.
_MWH_PER_MMBTU: float = 0.29307            # 1 MMBtu = 0.29307 MWh thermal (HHV)
_MMBTU_PER_TONNE_COAL: float = 24.0        # thermal coal HHV approx (Newcastle benchmark)
_MMBTU_PER_BARREL_BRENT: float = 5.80      # Brent crude HHV approx


# ---------------------------------------------------------------------------
# Fuel-price unit conversion: native units → ¥/MWh thermal (HHV)
# ---------------------------------------------------------------------------


def fuel_price_jpy_mwh_thermal(
    *,
    fuel_code: str,
    price: float,
    unit: str,
    fx_usdjpy: float,
) -> float:
    """Convert a `fuel_prices` row into ¥/MWh thermal (HHV).

    Args:
      fuel_code: 'lng_ccgt','lng_steam','coal','oil','nuclear', etc.
      price: native price value as stored in `fuel_prices.price`.
      unit: 'usd_mmbtu' | 'usd_t' | 'usd_bbl'.
      fx_usdjpy: USDJPY rate (yen per dollar).

    Returns:
      Cost of 1 MWh of fuel-thermal energy delivered, in JPY. The caller
      divides by the unit's `efficiency` to get electric ¥/MWh.

    Raises ValueError on unsupported (unit, fuel_code) combos so a config
    drift surfaces instead of producing a silent zero.
    """
    # Convert price to $/MMBtu first, then × FX, then × (1 / 0.29307 MWh/MMBtu).
    if unit == "usd_mmbtu":
        usd_per_mmbtu = price
    elif unit == "usd_t":
        if fuel_code != "coal":
            raise ValueError(f"$/t price unsupported for fuel {fuel_code}")
        usd_per_mmbtu = price / _MMBTU_PER_TONNE_COAL
    elif unit == "usd_bbl":
        if fuel_code != "oil":
            raise ValueError(f"$/bbl price unsupported for fuel {fuel_code}")
        usd_per_mmbtu = price / _MMBTU_PER_BARREL_BRENT
    else:
        raise ValueError(f"unsupported fuel-price unit: {unit!r}")

    jpy_per_mmbtu = usd_per_mmbtu * fx_usdjpy
    return jpy_per_mmbtu / _MWH_PER_MMBTU


# ---------------------------------------------------------------------------
# SRMC
# ---------------------------------------------------------------------------


# Fuel categories whose SRMC is effectively independent of fuel-price feeds.
_NEAR_ZERO_FUEL_CODES: frozenset[str] = frozenset(
    {"solar", "wind", "hydro", "geothermal", "biomass", "pumped_storage"}
)


def srmc_jpy_mwh(
    g: Generator,
    *,
    fuel_price_jpy_mwh_thermal: float | None,
) -> float:
    """Compute one generator's SRMC in ¥/MWh.

    Renewables and pumped storage return their `variable_om_jpy_mwh` only
    (effectively floor near zero). Nuclear uses variable_om as the all-in
    proxy. Fossil units use the standard formula; carbon price is hardcoded
    to 0 per v1 Japan reality.

    `fuel_price_jpy_mwh_thermal` may be None for non-fossil units; pass
    None to skip the fuel-cost branch.
    """
    if g.fuel_type_code in _NEAR_ZERO_FUEL_CODES:
        return float(g.variable_om_jpy_mwh or 0)

    if g.fuel_type_code == "nuclear":
        return float(g.variable_om_jpy_mwh or 0) + NUCLEAR_FUEL_CYCLE_JPY_MWH

    # Fossil. Need both fuel price and efficiency.
    if fuel_price_jpy_mwh_thermal is None:
        # Conservative: missing fuel price → push to top of merit order via
        # a sentinel high SRMC (¥99,999/MWh). The stack model will treat
        # the unit as unavailable for the slot rather than crash.
        return 99999.0
    if not g.efficiency or g.efficiency <= 0:
        return 99999.0

    fuel_cost = fuel_price_jpy_mwh_thermal / g.efficiency
    om_cost = float(g.variable_om_jpy_mwh or 0)
    co2_cost = float(g.co2_intensity_t_mwh or 0) * CARBON_PRICE_JPY_T
    return fuel_cost + om_cost + co2_cost
