/**
 * Canonical fuel-type → colour map. Reused by StackInspector chart, RegionDetail
 * gen-mix donut, and anywhere else fuels need a consistent visual identity.
 *
 * Values align with the conventional energy-data palette: greens for renewables,
 * cool blues for low-carbon thermal, greys for fossil, warm reds for oil/battery.
 */

export const FUEL_COLORS: Record<string, string> = {
  vre: "#22c55e",
  solar: "#facc15",
  wind: "#0ea5e9",
  nuclear: "#a855f7",
  hydro: "#06b6d4",
  pumped_storage: "#0ea5e9",
  geothermal: "#84cc16",
  biomass: "#65a30d",
  lng_ccgt: "#3b82f6",
  lng_steam: "#6366f1",
  coal: "#737373",
  oil: "#dc2626",
  battery: "#f59e0b",
  other: "#9ca3af",
};

export function fuelColor(code: string): string {
  return FUEL_COLORS[code] ?? FUEL_COLORS.other ?? "#999";
}
