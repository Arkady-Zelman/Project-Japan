import assert from "node:assert/strict";

import { runBoS, type AssetSpec, type ForwardPoint } from "./bos-strategy";

function slot(ix: number, price: number, vol = 0): ForwardPoint {
  return {
    ix,
    ts: new Date(Date.UTC(2026, 0, 1, ix, 0, 0)).toISOString(),
    price,
    vol,
  };
}

const lossyAsset: AssetSpec = {
  power_mw: 10,
  energy_mwh: 100,
  round_trip_eff: 0.85,
  soc_min_pct: 0,
  soc_max_pct: 1,
};

const falsePositiveSpread = runBoS([
  slot(0, 10),
  slot(1, 11),
], lossyAsset);

assert.equal(
  falsePositiveSpread.basket.length,
  0,
  "BoS must not commit a cash-negative cycle hidden by one-way efficiency",
);

const idealAsset: AssetSpec = {
  power_mw: 10,
  energy_mwh: 100,
  round_trip_eff: 1,
  soc_min_pct: 0,
  soc_max_pct: 1,
};

const overlappingCandidates = runBoS(
  [
    slot(0, 10, 0),
    slot(1, 12, 1_000_000),
    slot(2, 14.5, 0),
  ],
  idealAsset,
  { max_csos: 2 },
);

const chargeSlots = new Set(overlappingCandidates.basket.map((cso) => cso.charge_ix));
const dischargeSlots = new Set(overlappingCandidates.basket.map((cso) => cso.discharge_ix));
for (const ix of Array.from(chargeSlots)) {
  assert.ok(
    !dischargeSlots.has(ix),
    `BoS must not charge and discharge in the same slot (${ix})`,
  );
}
