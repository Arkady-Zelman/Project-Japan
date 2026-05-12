/**
 * Basket of Spreads (BoS) for battery storage — adapted from
 *   Baker, O'Brien, Ogden, Strickland: "Gas storage valuation strategies",
 *   Risk.net, November 2017.
 *
 * Treats each storage cycle as a long position in a calendar spread option
 * (CSO) — buy energy at a "charge" half-hour slot, sell at a "discharge"
 * half-hour slot. Each CSO is valued as a Bachelier spread option on the
 * two slot forwards.
 *
 * For BESS the optimal *intrinsic* basket is greedy in spread value, subject
 * to power-rate and capacity constraints (inventory must stay in [0, capacity]
 * at every intermediate slot). This relaxation matches the paper's
 * mixed-integer LP at the BESS-specific corner where volumes are continuous.
 * Extrinsic value is then layered on via the Bachelier at-the-money
 * approximation.
 *
 * Units: prices in JPY/kWh; volumes in MWh; all monetary outputs in JPY.
 * Time in half-hour slots (`dt_hours = 0.5`).
 */

export type ForwardPoint = {
  /** Index into the slot grid, 0..N-1. */
  ix: number;
  /** ISO timestamp for the slot start. */
  ts: string;
  /** Forward price (mean across paths or historical mean). JPY/kWh. */
  price: number;
  /** Standard deviation of price at this slot. JPY/kWh. */
  vol: number;
};

export type AssetSpec = {
  power_mw: number;
  energy_mwh: number;
  round_trip_eff: number;
  soc_min_pct: number;
  soc_max_pct: number;
  soc_initial_pct?: number;
};

export type CSO = {
  charge_ix: number;
  charge_ts: string;
  discharge_ix: number;
  discharge_ts: string;
  /** MWh charged at charge_ix. After round-trip loss this becomes volume_mwh*eta delivered at discharge_ix. */
  volume_mwh: number;
  /** F_discharge*eta - F_charge per kWh. JPY/kWh. */
  spread_jpy_kwh: number;
  spread_vol_jpy_kwh: number;
  intrinsic_jpy: number;
  extrinsic_jpy: number;
  total_jpy: number;
};

export type PhysicalDay = {
  date: string; // YYYY-MM-DD
  charge_mwh: number;
  discharge_mwh: number;
  inventory_end_mwh: number;
};

export type TradeableSlot = {
  ix: number;
  ts: string;
  forward_price: number;
  net_position_mwh: number; // + charge, - discharge
};

export type BoSResult = {
  source: "forecast" | "realised";
  asset_id: string | null;
  area: string;
  horizon_slots: number;
  dt_hours: number;
  total_intrinsic_jpy: number;
  total_extrinsic_jpy: number;
  total_value_jpy: number;
  basket: CSO[];
  physical: PhysicalDay[];
  tradeable: TradeableSlot[];
};

const SQRT_2PI = Math.sqrt(2 * Math.PI);
const KWH_PER_MWH = 1000;

/**
 * Run the BoS optimisation against a forward curve + asset.
 *
 * Implementation strategy:
 *  1. Enumerate every (i < j) pair, compute spread and spread-option value
 *     for one unit of charged energy.
 *  2. Sort candidates descending by per-unit total value.
 *  3. Greedy-allocate: for each candidate, add as much volume as power +
 *     capacity constraints permit. Skip if zero room remains.
 *  4. Compute per-day physical profile and per-slot tradeable view from
 *     the resulting basket.
 *
 * `corr_decay_hours` controls correlation between slots:
 *     rho(i, j) = exp(-|i - j| * dt_hours / corr_decay_hours)
 * Default 24h gives reasonable day-to-day decorrelation.
 */
export function runBoS(
  forward: ForwardPoint[],
  asset: AssetSpec,
  options: {
    dt_hours?: number;
    corr_decay_hours?: number;
    /** Cap on basket size; greedy stops once exhausted or this many CSOs added. */
    max_csos?: number;
  } = {},
): {
  total_intrinsic_jpy: number;
  total_extrinsic_jpy: number;
  total_value_jpy: number;
  basket: CSO[];
  physical: PhysicalDay[];
  tradeable: TradeableSlot[];
} {
  const dt = options.dt_hours ?? 0.5;
  const tau_h = options.corr_decay_hours ?? 24;
  const max_csos = options.max_csos ?? 80;

  const N = forward.length;
  const eta_one_way = Math.sqrt(asset.round_trip_eff);
  const eta_round_trip = asset.round_trip_eff;
  const max_charge_per_slot = asset.power_mw * dt; // MWh per slot
  const cap_min = asset.soc_min_pct * asset.energy_mwh;
  const cap_max = asset.soc_max_pct * asset.energy_mwh;
  const cap_room = cap_max - cap_min;

  // Running state across the greedy fill.
  const charge_at = new Array(N).fill(0); // MWh charged at slot i
  const discharge_at = new Array(N).fill(0); // MWh delivered at slot j
  // Cumulative inventory stored above cap_min at the end of each slot, before slot i+1.
  // We update this incrementally as we add CSOs.
  const inventory_after = new Array(N).fill(0);

  type Candidate = {
    i: number;
    j: number;
    spread: number; // JPY/kWh per unit charged
    spread_vol: number;
    intrinsic_per_unit_jpy: number; // JPY per MWh charged
    extrinsic_per_unit_jpy: number;
    total_per_unit_jpy: number;
  };

  const candidates: Candidate[] = [];
  for (let i = 0; i < N - 1; i++) {
    const fi = forward[i]!.price;
    const si = Math.max(forward[i]!.vol, 0);
    for (let j = i + 1; j < N; j++) {
      const fj = forward[j]!.price;
      const sj = Math.max(forward[j]!.vol, 0);
      // Per-kWh spread: deliver eta·F_j at discharge after paying F_i to charge.
      const spread = eta_one_way * fj - fi;
      // Per-kWh spread vol (Bachelier).
      const dh = (j - i) * dt;
      const rho = Math.exp(-dh / tau_h);
      const var_spread =
        si * si + (sj * eta_one_way) * (sj * eta_one_way) - 2 * rho * si * (sj * eta_one_way);
      const spread_vol = Math.sqrt(Math.max(var_spread, 0));
      // Bachelier valuation, K = 0, T = dh / 8760 (year fraction).
      const T_year = dh / 8760;
      const sigma_T = spread_vol * Math.sqrt(T_year);
      // Per-kWh option value with K=0:
      //   V = max(S, 0) + sigma*sqrt(T)*phi(d) - max(S,0)*N(-|d|)*sign(S)
      // Simpler ATM-style approximation: intrinsic + sigma*sqrt(T)/sqrt(2pi).
      const intrinsic_kwh = Math.max(spread, 0);
      const extrinsic_kwh = sigma_T / SQRT_2PI;
      const total_kwh = intrinsic_kwh + extrinsic_kwh;
      if (total_kwh <= 0) continue;
      candidates.push({
        i,
        j,
        spread,
        spread_vol,
        intrinsic_per_unit_jpy: intrinsic_kwh * KWH_PER_MWH,
        extrinsic_per_unit_jpy: extrinsic_kwh * KWH_PER_MWH,
        total_per_unit_jpy: total_kwh * KWH_PER_MWH,
      });
    }
  }
  candidates.sort((a, b) => b.total_per_unit_jpy - a.total_per_unit_jpy);

  const basket: CSO[] = [];

  for (const c of candidates) {
    if (basket.length >= max_csos) break;

    const room_charge = max_charge_per_slot - charge_at[c.i];
    const room_discharge = max_charge_per_slot - discharge_at[c.j];
    if (room_charge <= 1e-6 || room_discharge <= 1e-6) continue;

    // Inventory ceiling: max additional volume we can store between i and j-1.
    let max_inv_headroom = Infinity;
    for (let t = c.i; t < c.j; t++) {
      const headroom = cap_room - inventory_after[t];
      if (headroom < max_inv_headroom) max_inv_headroom = headroom;
    }
    if (max_inv_headroom <= 1e-6) continue;

    // Volume V (MWh charged): V·eta_one_way is added to inventory between [i, j-1].
    // V·eta_one_way ≤ max_inv_headroom → V ≤ max_inv_headroom / eta_one_way
    // V ≤ room_charge (charge-rate cap)
    // V·eta_round_trip ≤ room_discharge (discharge-rate cap)  → V ≤ room_discharge / eta_round_trip
    const V = Math.min(
      room_charge,
      room_discharge / eta_round_trip,
      max_inv_headroom / eta_one_way,
    );
    if (V <= 1e-6) continue;

    // Allocate.
    charge_at[c.i] += V;
    discharge_at[c.j] += V * eta_round_trip;
    const stored = V * eta_one_way;
    for (let t = c.i; t < c.j; t++) {
      inventory_after[t] += stored;
    }

    basket.push({
      charge_ix: c.i,
      charge_ts: forward[c.i]!.ts,
      discharge_ix: c.j,
      discharge_ts: forward[c.j]!.ts,
      volume_mwh: V,
      spread_jpy_kwh: c.spread,
      spread_vol_jpy_kwh: c.spread_vol,
      intrinsic_jpy: V * c.intrinsic_per_unit_jpy,
      extrinsic_jpy: V * c.extrinsic_per_unit_jpy,
      total_jpy: V * c.total_per_unit_jpy,
    });
  }

  const total_intrinsic_jpy = basket.reduce((s, b) => s + b.intrinsic_jpy, 0);
  const total_extrinsic_jpy = basket.reduce((s, b) => s + b.extrinsic_jpy, 0);
  const total_value_jpy = total_intrinsic_jpy + total_extrinsic_jpy;

  // Per-day physical profile.
  const by_day = new Map<string, { charge: number; discharge: number }>();
  for (let i = 0; i < N; i++) {
    const day = forward[i]!.ts.slice(0, 10);
    const cur = by_day.get(day) ?? { charge: 0, discharge: 0 };
    cur.charge += charge_at[i];
    cur.discharge += discharge_at[i];
    by_day.set(day, cur);
  }
  const physical: PhysicalDay[] = [];
  let running_inv = cap_min;
  for (const i of forward.map((_, k) => k)) {
    // Track inventory end of each day at the day's last slot.
    const day = forward[i]!.ts.slice(0, 10);
    running_inv += charge_at[i] * eta_one_way - discharge_at[i] / eta_one_way;
    const nextSameDay = i + 1 < N && forward[i + 1]!.ts.slice(0, 10) === day;
    if (!nextSameDay) {
      const d = by_day.get(day);
      if (d) {
        physical.push({
          date: day,
          charge_mwh: d.charge,
          discharge_mwh: d.discharge,
          inventory_end_mwh: running_inv,
        });
      }
    }
  }

  // Per-slot tradeable view.
  const tradeable: TradeableSlot[] = forward.map((f, i) => ({
    ix: i,
    ts: f.ts,
    forward_price: f.price,
    net_position_mwh: charge_at[i] - discharge_at[i],
  }));

  return {
    total_intrinsic_jpy,
    total_extrinsic_jpy,
    total_value_jpy,
    basket,
    physical,
    tradeable,
  };
}
