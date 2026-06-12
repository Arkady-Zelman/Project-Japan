import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { runBoS, type ForwardPoint } from "./bos-strategy";

function forward(prices: number[]): ForwardPoint[] {
  return prices.map((price, ix) => ({
    ix,
    ts: new Date(Date.UTC(2026, 0, 1, 0, ix * 30)).toISOString(),
    price,
    vol: 0,
  }));
}

describe("runBoS", () => {
  it("values BESS spreads with round-trip efficiency", () => {
    const result = runBoS(
      forward([10, 12]),
      {
        power_mw: 10,
        energy_mwh: 100,
        round_trip_eff: 0.85,
        soc_min_pct: 0,
        soc_max_pct: 1,
      },
      { dt_hours: 0.5 },
    );

    assert.equal(result.basket.length, 1);
    assert.ok(Math.abs((result.basket[0]?.spread_jpy_kwh ?? 0) - 0.2) < 1e-9);
    assert.ok(Math.abs(result.total_intrinsic_jpy - 1000) < 1e-6);
  });

  it("does not allocate spreads that are only profitable under one-way efficiency", () => {
    const result = runBoS(
      forward([10, 11.5]),
      {
        power_mw: 10,
        energy_mwh: 100,
        round_trip_eff: 0.85,
        soc_min_pct: 0,
        soc_max_pct: 1,
      },
      { dt_hours: 0.5 },
    );

    assert.equal(result.basket.length, 0);
    assert.equal(result.total_intrinsic_jpy, 0);
  });
});
