"use client";

/**
 * Strategy tab — Basket of Spreads (BoS) for storage assets.
 *
 * Reference: Baker, O'Brien, Ogden, Strickland, "Gas storage valuation
 * strategies", Risk.net Nov 2017. We adapt the CSO basket framework to
 * half-hourly BESS dispatch:
 *   - Forward curve per slot from VLSTM forecast paths (default) or 28-day
 *     realised JEPX (toggle).
 *   - One row per optimal calendar-spread option in the basket.
 *   - Tradeable view: aggregated per-slot net position.
 *   - Physical view: daily injection / withdrawal / inventory profile.
 */

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useCallback, useEffect, useMemo, useState } from "react";

import { MetricCard } from "@/components/ui/metric-card";
import { Skeleton } from "@/components/ui/skeleton";

type Forecast = "forecast" | "realised";

type CSO = {
  charge_ix: number;
  charge_ts: string;
  discharge_ix: number;
  discharge_ts: string;
  volume_mwh: number;
  spread_jpy_kwh: number;
  spread_vol_jpy_kwh: number;
  intrinsic_jpy: number;
  extrinsic_jpy: number;
  total_jpy: number;
};

type PhysicalDay = {
  date: string;
  charge_mwh: number;
  discharge_mwh: number;
  inventory_end_mwh: number;
};

type TradeableSlot = {
  ix: number;
  ts: string;
  forward_price: number;
  net_position_mwh: number;
};

type BoSResponse = {
  source: Forecast;
  asset: { id: string; name: string; area: string; power_mw: number; energy_mwh: number; round_trip_eff: number };
  horizon_slots: number;
  dt_hours: number;
  total_intrinsic_jpy: number;
  total_extrinsic_jpy: number;
  total_value_jpy: number;
  basket: CSO[];
  physical: PhysicalDay[];
  tradeable: TradeableSlot[];
};

function fmtJpy(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `¥${(v / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `¥${(v / 1_000).toFixed(1)}k`;
  return `¥${v.toFixed(0)}`;
}

function fmtSlot(ts: string): string {
  // e.g. "May 13, 09:30"
  const d = new Date(ts);
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const day = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${month} ${day}, ${hh}:${mm}`;
}

export function StrategyTab() {
  const [source, setSource] = useState<Forecast>("forecast");
  const [horizon, setHorizon] = useState<number>(48);
  const [data, setData] = useState<BoSResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchBos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`/api/bos-strategy?source=${source}&horizon_slots=${horizon}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j?.error?.toString() ?? r.statusText);
      setData(j as BoSResponse);
    } catch (e) {
      setError(String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [source, horizon]);

  useEffect(() => {
    void fetchBos();
  }, [fetchBos]);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight">Basket of Spreads</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Decomposes storage value into a portfolio of calendar spread options on the slot
          forwards (one CSO per charge → discharge pair). Adapted from Baker/O&apos;Brien/Ogden/
          Strickland, &ldquo;Gas storage valuation strategies&rdquo;, Risk.net Nov 2017. Built greedy in
          spread value under power + inventory constraints; extrinsic value layered via
          Bachelier at-the-money approximation.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
        <div>
          <label className="mb-1 block text-xs uppercase tracking-wide text-muted-foreground">
            Forward curve source
          </label>
          <div className="flex items-center gap-1 rounded-md bg-muted p-1">
            {(["forecast", "realised"] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSource(s)}
                className={`rounded px-3 py-1.5 text-xs font-medium transition ${
                  source === s
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {s === "forecast" ? "VLSTM forecast" : "Realised (28d)"}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="mb-1 block text-xs uppercase tracking-wide text-muted-foreground">
            Horizon
          </label>
          <select
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value))}
            className="rounded-md border border-foreground/10 bg-background px-3 py-1.5 text-sm"
          >
            <option value={48}>1 day (48 slots)</option>
            <option value={96}>2 days</option>
            <option value={168}>3.5 days</option>
            <option value={336}>7 days</option>
          </select>
        </div>
        <button
          type="button"
          onClick={() => void fetchBos()}
          disabled={loading}
          className="rounded-md border border-foreground/10 px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50"
        >
          {loading ? "Computing…" : "Recompute"}
        </button>
        {data?.asset && (
          <div className="ml-auto text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{data.asset.name}</span> ·{" "}
            <span className="font-mono">{data.asset.area}</span> · {data.asset.power_mw} MW /{" "}
            {data.asset.energy_mwh} MWh · η={data.asset.round_trip_eff.toFixed(2)}
          </div>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2 text-sm text-red-500">
          {error}
        </div>
      )}

      {loading && !data && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
          <Skeleton className="h-[280px] w-full" />
          <Skeleton className="h-[260px] w-full" />
        </div>
      )}

      {data && (
        <>
          <ScheduleSummary data={data} />

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <MetricCard
              label="BoS total value"
              value={fmtJpy(data.total_value_jpy)}
              hint={`across ${data.basket.length} CSOs`}
              tone="positive"
            />
            <MetricCard label="Intrinsic" value={fmtJpy(data.total_intrinsic_jpy)} />
            <MetricCard label="Extrinsic" value={fmtJpy(data.total_extrinsic_jpy)} />
            <MetricCard
              label="Per kWh of capacity"
              value={
                data.asset.energy_mwh > 0
                  ? fmtJpy(data.total_value_jpy / (data.asset.energy_mwh * 1000))
                  : "—"
              }
              unit="JPY/kWh"
            />
          </div>

          <PhysicalProfile data={data} />

          <ExpectedPnL data={data} />

          <BasketTable basket={data.basket} />
        </>
      )}
    </div>
  );
}

function fmtHHMM(ts: string): string {
  const d = new Date(ts);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

/**
 * Date-aware slot label. Falls back to `HH:MM` when every slot in the
 * series falls on the same UTC calendar day; otherwise prepends MM-DD so
 * the X-axis distinguishes Day 1 11:30 from Day 2 11:30.
 */
function buildSlotLabeler(tradeable: { ts: string }[]): (ts: string) => string {
  const days = new Set<string>();
  for (const s of tradeable) days.add(s.ts.slice(0, 10));
  const multiDay = days.size > 1;
  if (!multiDay) return fmtHHMM;
  return (ts: string) => {
    const d = new Date(ts);
    const mo = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mm = String(d.getUTCMinutes()).padStart(2, "0");
    return `${mo}-${dd} ${hh}:${mm}`;
  };
}

function PhysicalProfile({ data }: { data: BoSResponse }) {
  const dtHours = data.dt_hours ?? 0.5;
  const labeler = useMemo(() => buildSlotLabeler(data.tradeable), [data.tradeable]);
  const chartData = useMemo(() => {
    // Running inventory in MWh through the half-hourly schedule.
    const eta = Math.sqrt(data.asset.round_trip_eff);
    let inv = 0;
    return data.tradeable.map((s) => {
      const charge = s.net_position_mwh > 0 ? s.net_position_mwh : 0;
      const discharge = s.net_position_mwh < 0 ? -s.net_position_mwh : 0;
      inv += charge * eta - discharge / eta;
      return {
        ts: s.ts,
        label: labeler(s.ts),
        charge: Math.round(charge * 10) / 10,
        discharge: -Math.round(discharge * 10) / 10,
        inventory: Math.round(inv * 10) / 10,
        price: s.forward_price,
      };
    });
  }, [data]);

  // Show ~12 labels max regardless of horizon, every Nth tick.
  const tickInterval = Math.max(0, Math.floor(chartData.length / 12) - 1);

  return (
    <div className="rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <h3 className="mb-1 text-base font-medium">Physical profile</h3>
      <p className="mb-3 text-xs text-muted-foreground">
        Half-hourly charge (green, up) / discharge (red, down) and running inventory (blue line) over
        the {dtHours === 0.5 ? `${data.tradeable.length / 2}-hour` : `${data.tradeable.length}-slot`} horizon.
      </p>
      <div className="h-[320px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 8, right: 16, bottom: 56, left: 8 }}>
            <CartesianGrid stroke="#262626" strokeDasharray="3 3" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: "#a3a3a3" }}
              angle={-90}
              textAnchor="end"
              interval={tickInterval}
              height={56}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#a3a3a3" }}
              tickFormatter={(v) => `${Math.round(v as number)}`}
              label={{ value: "MWh", angle: -90, position: "insideLeft", fill: "#a3a3a3", fontSize: 11 }}
            />
            <ReTooltip
              contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }}
              labelStyle={{ color: "#fafafa" }}
              formatter={(v, name) => {
                const n = Number(v);
                if (!Number.isFinite(n)) return ["—", String(name)];
                if (name === "Inventory") return [`${n.toFixed(1)} MWh`, name];
                return [`${Math.abs(n).toFixed(1)} MWh`, String(name)];
              }}
            />
            <Bar dataKey="charge" name="Charge" fill="#22c55e" isAnimationActive={false} />
            <Bar dataKey="discharge" name="Discharge" fill="#dc2626" isAnimationActive={false} />
            <Line
              type="monotone"
              dataKey="inventory"
              name="Inventory"
              stroke="#1d4ed8"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function ExpectedPnL({ data }: { data: BoSResponse }) {
  const labeler = useMemo(() => buildSlotLabeler(data.tradeable), [data.tradeable]);
  const chartData = useMemo(() => {
    let cum = 0;
    let cumCharge = 0;
    let cumDischarge = 0;
    return data.tradeable.map((s) => {
      // net_position_mwh > 0 → we charge (cash out, NEGATIVE cashflow).
      // net_position_mwh < 0 → we discharge (cash in, POSITIVE cashflow).
      const cashflow_jpy = -s.net_position_mwh * s.forward_price * 1000;
      cum += cashflow_jpy;
      if (s.net_position_mwh > 0) cumCharge += -cashflow_jpy;
      else if (s.net_position_mwh < 0) cumDischarge += cashflow_jpy;
      return {
        ts: s.ts,
        label: labeler(s.ts),
        cum_pnl: Math.round(cum),
        cum_charge_cost: -Math.round(cumCharge),
        cum_discharge_rev: Math.round(cumDischarge),
        price: s.forward_price,
      };
    });
  }, [data]);

  const tickInterval = Math.max(0, Math.floor(chartData.length / 12) - 1);
  const final = chartData[chartData.length - 1];

  return (
    <div className="rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h3 className="text-base font-medium">Expected P&amp;L over time</h3>
          <p className="text-xs text-muted-foreground">
            Cumulative cashflow while executing the basket against the forward curve.
            Down-slopes are charge slots (paying for energy); up-slopes are discharge
            slots (revenue).
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-xs">
          <span>
            Charge spend{" "}
            <span className="font-mono text-red-400">
              {fmtJpy(Math.abs(final?.cum_charge_cost ?? 0))}
            </span>
          </span>
          <span>
            Discharge revenue{" "}
            <span className="font-mono text-emerald-400">
              {fmtJpy(final?.cum_discharge_rev ?? 0)}
            </span>
          </span>
          <span>
            Final P&amp;L{" "}
            <span className="font-mono font-semibold text-foreground">
              {fmtJpy(final?.cum_pnl ?? 0)}
            </span>
          </span>
        </div>
      </header>
      <div className="h-[280px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 8, right: 16, bottom: 56, left: 8 }}>
            <CartesianGrid stroke="#262626" strokeDasharray="3 3" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: "#a3a3a3" }}
              angle={-90}
              textAnchor="end"
              interval={tickInterval}
              height={56}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#a3a3a3" }}
              tickFormatter={(v) => {
                const n = Number(v);
                if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
                if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
                return `${n}`;
              }}
              label={{
                value: "JPY",
                angle: -90,
                position: "insideLeft",
                fill: "#a3a3a3",
                fontSize: 11,
              }}
            />
            <ReTooltip
              contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }}
              labelStyle={{ color: "#fafafa" }}
              formatter={(v) => fmtJpy(Number(v))}
            />
            <Line
              type="monotone"
              dataKey="cum_pnl"
              name="Cumulative P&L"
              stroke="#1d4ed8"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="cum_discharge_rev"
              name="Cum. discharge revenue"
              stroke="#22c55e"
              strokeWidth={1.5}
              strokeDasharray="3 3"
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="cum_charge_cost"
              name="Cum. charge spend"
              stroke="#dc2626"
              strokeWidth={1.5}
              strokeDasharray="3 3"
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-[#1d4ed8]" /> Cumulative P&amp;L
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 border-t border-dashed border-[#22c55e]" />{" "}
          Cum. discharge revenue
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 border-t border-dashed border-[#dc2626]" />{" "}
          Cum. charge spend (negative)
        </span>
        <span className="ml-auto">
          Intrinsic target {fmtJpy(data.total_intrinsic_jpy)} · BoS total{" "}
          {fmtJpy(data.total_value_jpy)}
        </span>
      </div>
    </div>
  );
}

/**
 * Top-of-tab plain-English summary + colour-coded timeline strip.
 * Each cell = one half-hour slot, coloured by what the basket says to do.
 */
function ScheduleSummary({ data }: { data: BoSResponse }) {
  const slots = data.tradeable;
  if (slots.length === 0) return null;

  // Aggregate into contiguous "windows" of consecutive same-action slots.
  type Window = { kind: "charge" | "discharge" | "idle"; from: string; to: string; mwh: number; avgPrice: number };
  const windows: Window[] = [];
  let current: Window | null = null;
  for (const s of slots) {
    const kind: Window["kind"] =
      s.net_position_mwh > 1e-6 ? "charge" : s.net_position_mwh < -1e-6 ? "discharge" : "idle";
    const mw = Math.abs(s.net_position_mwh);
    if (!current || current.kind !== kind) {
      if (current) windows.push(current);
      current = { kind, from: s.ts, to: s.ts, mwh: mw, avgPrice: s.forward_price * mw };
    } else {
      current.to = s.ts;
      current.mwh += mw;
      current.avgPrice += s.forward_price * mw;
    }
  }
  if (current) windows.push(current);
  for (const w of windows) {
    w.avgPrice = w.mwh > 0 ? w.avgPrice / w.mwh : 0;
  }

  // Headline numbers.
  const totalCharge = windows
    .filter((w) => w.kind === "charge")
    .reduce((s, w) => s + w.mwh, 0);
  const totalDischarge = windows
    .filter((w) => w.kind === "discharge")
    .reduce((s, w) => s + w.mwh, 0);
  const eta = Math.sqrt(data.asset.round_trip_eff);
  const peakInv = (() => {
    let inv = 0;
    let peak = 0;
    for (const s of slots) {
      const c = s.net_position_mwh > 0 ? s.net_position_mwh : 0;
      const d = s.net_position_mwh < 0 ? -s.net_position_mwh : 0;
      inv += c * eta - d / eta;
      if (inv > peak) peak = inv;
    }
    return peak;
  })();
  const cycles = data.asset.energy_mwh > 0 ? totalDischarge / data.asset.energy_mwh : 0;

  // For each window, compute its share of the strip width.
  const totalDuration = slots.length;

  // Hour markers every ~2 hours.
  const hourTicks: { ix: number; label: string }[] = [];
  for (let i = 0; i < slots.length; i++) {
    const d = new Date(slots[i]!.ts);
    if (d.getUTCMinutes() === 0 && d.getUTCHours() % 2 === 0) {
      hourTicks.push({ ix: i, label: `${String(d.getUTCHours()).padStart(2, "0")}:00` });
    }
  }

  const chargeWindows = windows.filter((w) => w.kind === "charge");
  const dischargeWindows = windows.filter((w) => w.kind === "discharge");
  const avgChargePrice =
    chargeWindows.reduce((s, w) => s + w.avgPrice * w.mwh, 0) / Math.max(totalCharge, 1e-9);
  const avgDischargePrice =
    dischargeWindows.reduce((s, w) => s + w.avgPrice * w.mwh, 0) /
    Math.max(totalDischarge, 1e-9);

  return (
    <section className="rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <header className="mb-3 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-medium">Today&apos;s schedule</h3>
          <p className="text-xs text-muted-foreground">
            Action implied by the optimal basket at each half-hour slot.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block size-2.5 rounded-sm bg-emerald-500" /> Charge
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block size-2.5 rounded-sm bg-red-500" /> Discharge
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block size-2.5 rounded-sm bg-neutral-700" /> Idle
          </span>
        </div>
      </header>

      <p className="mb-3 text-sm leading-relaxed">
        Charge <span className="font-semibold text-emerald-400">{totalCharge.toFixed(1)} MWh</span>{" "}
        in {chargeWindows.length} window{chargeWindows.length === 1 ? "" : "s"} at average{" "}
        <span className="font-mono">¥{avgChargePrice.toFixed(2)}/kWh</span>; discharge{" "}
        <span className="font-semibold text-red-400">{totalDischarge.toFixed(1)} MWh</span> in{" "}
        {dischargeWindows.length} window{dischargeWindows.length === 1 ? "" : "s"} at average{" "}
        <span className="font-mono">¥{avgDischargePrice.toFixed(2)}/kWh</span>. Peak inventory{" "}
        <span className="font-semibold">{peakInv.toFixed(1)} MWh</span> ({((peakInv / data.asset.energy_mwh) * 100).toFixed(0)}% SoC) ·{" "}
        {cycles.toFixed(2)} full cycle{cycles >= 1.5 || cycles < 0.5 ? "s" : ""}.
      </p>

      {/* Colour-coded timeline strip */}
      <div className="relative h-8 w-full overflow-hidden rounded-md ring-1 ring-foreground/10">
        <div className="flex h-full w-full">
          {slots.map((s, i) => {
            const c =
              s.net_position_mwh > 1e-6
                ? "bg-emerald-500"
                : s.net_position_mwh < -1e-6
                  ? "bg-red-500"
                  : "bg-neutral-800";
            return (
              <div
                key={i}
                title={`${fmtHHMM(s.ts)} · ${s.net_position_mwh > 0 ? "charge" : s.net_position_mwh < 0 ? "discharge" : "idle"} ${Math.abs(s.net_position_mwh).toFixed(1)} MWh · forward ¥${s.forward_price.toFixed(2)}/kWh`}
                className={`${c} h-full`}
                style={{ width: `${100 / totalDuration}%` }}
              />
            );
          })}
        </div>
      </div>
      {/* Hour ticks below the strip */}
      <div className="relative mt-1 h-4 w-full text-[10px] text-muted-foreground">
        {hourTicks.map((t) => (
          <span
            key={t.ix}
            className="absolute -translate-x-1/2"
            style={{ left: `${((t.ix + 0.5) / totalDuration) * 100}%` }}
          >
            {t.label}
          </span>
        ))}
      </div>

      {/* Window-by-window list (truncated to the largest few). */}
      <ul className="mt-4 grid grid-cols-1 gap-2 text-xs md:grid-cols-2">
        {windows
          .filter((w) => w.kind !== "idle" && w.mwh > 0.5)
          .slice(0, 8)
          .map((w, i) => (
            <li key={i} className="flex items-center gap-2 rounded-md bg-muted/30 px-2 py-1.5">
              <span
                className={`inline-block size-2 rounded-full ${
                  w.kind === "charge" ? "bg-emerald-500" : "bg-red-500"
                }`}
              />
              <span className="font-medium capitalize">{w.kind}</span>
              <span className="font-mono">
                {fmtHHMM(w.from)}–{fmtHHMM(w.to)}
              </span>
              <span className="ml-auto tabular-nums">{w.mwh.toFixed(1)} MWh · ¥{w.avgPrice.toFixed(2)}/kWh</span>
            </li>
          ))}
      </ul>
    </section>
  );
}

function BasketTable({ basket }: { basket: CSO[] }) {
  return (
    <div className="rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <h3 className="mb-1 text-base font-medium">Basket composition</h3>
      <p className="mb-3 text-xs text-muted-foreground">
        Optimal CSO portfolio sorted by total value (intrinsic + extrinsic). Each row pairs
        a charge slot with a discharge slot at the volume that maximises value without
        violating power-rate or capacity constraints.
      </p>
      {basket.length === 0 ? (
        <p className="text-sm text-muted-foreground">No profitable spreads in this horizon.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-1.5 pr-3 font-medium">Charge slot</th>
                <th className="py-1.5 pr-3 font-medium">Discharge slot</th>
                <th className="py-1.5 pr-3 font-medium text-right">Volume (MWh)</th>
                <th className="py-1.5 pr-3 font-medium text-right">Spread (¥/kWh)</th>
                <th className="py-1.5 pr-3 font-medium text-right">σ_spread (¥/kWh)</th>
                <th className="py-1.5 pr-3 font-medium text-right">Intrinsic</th>
                <th className="py-1.5 pr-3 font-medium text-right">Extrinsic</th>
                <th className="py-1.5 font-medium text-right">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-foreground/5">
              {basket.map((c, i) => (
                <tr key={i}>
                  <td className="py-1.5 pr-3 font-mono">{fmtSlot(c.charge_ts)}</td>
                  <td className="py-1.5 pr-3 font-mono">{fmtSlot(c.discharge_ts)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {c.volume_mwh.toFixed(1)}
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {c.spread_jpy_kwh.toFixed(2)}
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-muted-foreground">
                    {c.spread_vol_jpy_kwh.toFixed(2)}
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{fmtJpy(c.intrinsic_jpy)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-muted-foreground">
                    {fmtJpy(c.extrinsic_jpy)}
                  </td>
                  <td className="py-1.5 text-right tabular-nums font-medium">
                    {fmtJpy(c.total_jpy)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
