"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { FUEL_COLORS } from "@/lib/fuel-colors";

const SELECT_CLS =
  "w-full appearance-none rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring";

const AREAS = [
  { code: "TK", name: "Tokyo" },
  { code: "HK", name: "Hokkaido" },
  { code: "TH", name: "Tohoku" },
  { code: "CB", name: "Chubu" },
  { code: "HR", name: "Hokuriku" },
  { code: "KS", name: "Kansai" },
  { code: "CG", name: "Chugoku" },
  { code: "SK", name: "Shikoku" },
  { code: "KY", name: "Kyushu" },
] as const;
type AreaCode = (typeof AREAS)[number]["code"];

type CurveStep = {
  mw_cumulative: number;
  srmc_jpy_mwh: number;
  generator_id: string | null;
  fuel_code: string;
  name: string;
};

type Clearing = {
  modelled_price_jpy_mwh: number | null;
  modelled_demand_mw: number | null;
  marginal_unit_id: string | null;
};

type StackResponse = {
  area: { id: string; code: string; name_en: string };
  slot: string;
  curve: CurveStep[] | null;
  inputs_hash: string | null;
  clearing: Clearing | null;
  marginal_unit_name: string | null;
  realised_jpy_kwh: number | null;
};

function todaySlotIso(): string {
  // Default to yesterday 12:00 JST = 03:00 UTC.
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 1);
  d.setUTCHours(3, 0, 0, 0);
  return d.toISOString();
}

function buildSlotOptions(date: string): { label: string; value: string }[] {
  // 48 half-hourly slots in JST starting at 00:00 JST = 15:00 UTC previous day.
  const baseUtc = new Date(date + "T15:00:00Z");
  const out: { label: string; value: string }[] = [];
  for (let i = 0; i < 48; i++) {
    const t = new Date(baseUtc.getTime() + i * 30 * 60 * 1000);
    const jst = new Date(t.getTime() + 9 * 60 * 60 * 1000);
    const hh = String(jst.getUTCHours()).padStart(2, "0");
    const mm = String(jst.getUTCMinutes()).padStart(2, "0");
    out.push({ label: `${hh}:${mm} JST`, value: t.toISOString() });
  }
  return out;
}

export function StackInspector() {
  const [area, setArea] = useState<AreaCode>("TK");
  const [date, setDate] = useState<string>(() => {
    // Yesterday in JST as a placeholder; replaced on mount by the
    // latest-slot lookup below.
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [slot, setSlot] = useState<string>(todaySlotIso);
  // Seeded state — true until the latest-slot lookup resolves at least
  // once so we don't fire two consecutive /api/stack-curve fetches
  // (placeholder → real) on first render.
  const [seeded, setSeeded] = useState(false);
  // Slots-with-data for the currently selected (area, date). Populated by a
  // /api/stack-curve/slots fetch whenever those change; the dropdown shows
  // ONLY these slots so the operator can't pick an empty cell.
  const [availableSlots, setAvailableSlots] = useState<string[] | null>(null);

  const slotOptions = useMemo(() => {
    if (availableSlots) {
      return availableSlots.map((iso) => {
        const jst = new Date(new Date(iso).getTime() + 9 * 60 * 60 * 1000);
        const hh = String(jst.getUTCHours()).padStart(2, "0");
        const mm = String(jst.getUTCMinutes()).padStart(2, "0");
        return { label: `${hh}:${mm} JST`, value: iso };
      });
    }
    // Fallback while loading or for areas with zero coverage in the date.
    return buildSlotOptions(date);
  }, [availableSlots, date]);

  const [data, setData] = useState<StackResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // On mount + on area change, ask the server for the latest slot that
  // actually has a stack curve. Seeds the date + slot pickers so the tab
  // opens to live data instead of an empty slot.
  useEffect(() => {
    let cancelled = false;
    fetch(`/api/stack-curve/latest?area=${area}`)
      .then(async (r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (cancelled || !j?.slot) {
          setSeeded(true);
          return;
        }
        const iso: string = j.slot;
        setSlot(iso);
        setDate(iso.slice(0, 10));
        setSeeded(true);
      })
      .catch(() => {
        if (!cancelled) setSeeded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [area]);

  // Refetch the available-slots list whenever (area, date) changes. Snap the
  // current slot to whatever's in the list (closest match) so we never have
  // a stale `slot` value pointing at an empty cell.
  useEffect(() => {
    let cancelled = false;
    setAvailableSlots(null);
    fetch(`/api/stack-curve/slots?area=${area}&date=${date}`)
      .then(async (r) => (r.ok ? r.json() : { slots: [] }))
      .then((j) => {
        if (cancelled) return;
        const slots = (j.slots ?? []) as string[];
        setAvailableSlots(slots);
        // If current `slot` isn't in the list, snap to the first available
        // (or leave alone if the list is empty so the empty-state renders).
        if (slots.length > 0 && !slots.includes(slot)) {
          setSlot(slots[0]!);
        }
      })
      .catch(() => {
        if (!cancelled) setAvailableSlots([]);
      });
    return () => {
      cancelled = true;
    };
  }, [area, date, slot]);

  useEffect(() => {
    if (!seeded) return;
    setLoading(true);
    setError(null);
    fetch(`/api/stack-curve?area=${area}&slot=${encodeURIComponent(slot)}`)
      .then(async (r) => {
        const j = await r.json();
        if (!r.ok) throw new Error(j?.error?.toString() ?? r.statusText);
        return j as StackResponse;
      })
      .then((d) => setData(d))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [area, slot, seeded]);

  const chartData = useMemo(() => {
    // Recharts stepAfter wants (x_n, y_n) where y_n is held from x_{n-1} to x_n.
    // For our merit-order curve we want each step to render as a horizontal
    // run at its SRMC followed by a vertical jump up at the right edge.
    // Encode as (mw_left_edge, srmc_of_step).
    if (!data?.curve || data.curve.length === 0) return [];
    const rows: { mw: number; srmc: number; fuel: string; name: string }[] = [];
    let prevMw = 0;
    for (const step of data.curve) {
      rows.push({
        mw: prevMw,
        srmc: step.srmc_jpy_mwh,
        fuel: step.fuel_code,
        name: step.name,
      });
      prevMw = step.mw_cumulative;
    }
    // Terminating point so the last horizontal run reaches the right edge.
    const last = data.curve[data.curve.length - 1];
    if (last) {
      rows.push({
        mw: last.mw_cumulative,
        srmc: last.srmc_jpy_mwh,
        fuel: last.fuel_code,
        name: last.name,
      });
    }
    return rows;
  }, [data]);

  // Clamp Y axis so the marginal unit is visible even when the curve has a
  // sentinel-high tail (e.g. ¥99,999/MWh for a unit with missing fuel price).
  const yMax = useMemo(() => {
    if (!data?.clearing?.modelled_price_jpy_mwh) {
      // No clearing → fall back to 30,000 ¥/MWh which covers normal LNG SRMC.
      return 30000;
    }
    return Math.max(data.clearing.modelled_price_jpy_mwh * 1.4, 5000);
  }, [data]);

  const xMax = useMemo(() => {
    if (!data?.curve || data.curve.length === 0) return 1;
    const last = data.curve[data.curve.length - 1];
    if (!last) return 1;
    const demand = data.clearing?.modelled_demand_mw ?? null;
    if (demand && demand > 0) return Math.min(last.mw_cumulative, demand * 1.3);
    return last.mw_cumulative;
  }, [data]);

  const modelledKwh = data?.clearing?.modelled_price_jpy_mwh
    ? data.clearing.modelled_price_jpy_mwh / 1000
    : null;
  const realisedKwh = data?.realised_jpy_kwh ?? null;
  const gap =
    modelledKwh != null && realisedKwh != null ? realisedKwh - modelledKwh : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Section C — Stack inspector</CardTitle>
        <CardDescription>
          Merit-order supply curve for the selected slot. Step chart by SRMC;
          horizontal line is metered demand. The marginal unit is highlighted.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Area</label>
            <select
              className={SELECT_CLS}
              value={area}
              onChange={(e) => setArea(e.target.value as AreaCode)}
            >
              {AREAS.map((a) => (
                <option key={a.code} value={a.code}>
                  {a.name} ({a.code})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Date (JST)</label>
            <input
              type="date"
              value={date}
              onChange={(e) => {
                setDate(e.target.value);
                // Reset slot to start of day.
                const ev = e.target.value;
                const baseUtc = new Date(ev + "T15:00:00Z");
                setSlot(baseUtc.toISOString());
              }}
              className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Half-hour slot</label>
            <select
              className={SELECT_CLS}
              value={slot}
              onChange={(e) => setSlot(e.target.value)}
            >
              {slotOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <Separator />

        {loading && (
          <div className="space-y-2">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-[400px] w-full" />
          </div>
        )}
        {error && <p className="text-sm text-red-600">Error: {error}</p>}

        {data && data.curve && data.curve.length > 0 ? (
          <>
            <div className="h-[400px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 16, right: 24, bottom: 36, left: 64 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis
                    type="number"
                    dataKey="mw"
                    label={{
                      value: "Cumulative dispatch (MW)",
                      position: "insideBottom",
                      offset: -22,
                      style: { textAnchor: "middle" },
                    }}
                    domain={[0, xMax]}
                    tickFormatter={(v) => Math.round(v as number).toLocaleString()}
                  />
                  <YAxis
                    label={{
                      value: "SRMC (¥/MWh)",
                      angle: -90,
                      position: "insideLeft",
                      offset: -42,
                      style: { textAnchor: "middle" },
                    }}
                    domain={[0, yMax]}
                    tickFormatter={(v) => Math.round(v as number).toLocaleString()}
                    width={60}
                  />
                  <ReTooltip
                    formatter={(value, _name, item) => {
                      const v = typeof value === "number" ? value : Number(value);
                      const payload = (item as { payload?: { fuel?: string; name?: string } })?.payload;
                      const fuel = payload?.fuel ?? "";
                      const nm = payload?.name ?? "";
                      return [`¥${v.toFixed(0)}/MWh`, `${nm} (${fuel})`];
                    }}
                    labelFormatter={(label) => {
                      const v = typeof label === "number" ? label : Number(label);
                      return `at ${Number.isFinite(v) ? v.toFixed(0) : "—"} MW`;
                    }}
                  />
                  <Line
                    type="stepAfter"
                    dataKey="srmc"
                    stroke="#2563eb"
                    dot={{ r: 3, fill: "#2563eb", stroke: "#2563eb" }}
                    activeDot={{ r: 5 }}
                    strokeWidth={2.5}
                    isAnimationActive={false}
                  />
                  {data.clearing?.modelled_demand_mw && (
                    <ReferenceLine
                      x={data.clearing.modelled_demand_mw}
                      stroke="#dc2626"
                      strokeDasharray="4 4"
                      label={{ value: "demand", position: "top", fill: "#dc2626" }}
                    />
                  )}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <Separator />
            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <div>
                <div className="text-xs text-muted-foreground">Modelled clearing</div>
                <div className="font-medium">
                  {modelledKwh != null ? `¥${modelledKwh.toFixed(2)}/kWh` : "—"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Realised JEPX</div>
                <div className="font-medium">
                  {realisedKwh != null ? `¥${realisedKwh.toFixed(2)}/kWh` : "—"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Gap</div>
                <div className="font-medium">
                  {gap != null ? `¥${gap.toFixed(2)}/kWh` : "—"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Marginal unit</div>
                <div className="font-medium">{data.marginal_unit_name ?? "—"}</div>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {Array.from(new Set(data.curve.map((s) => s.fuel_code))).map((f) => (
                <Badge
                  key={f}
                  style={{ backgroundColor: FUEL_COLORS[f] ?? "#999", color: "#fff" }}
                  className="border-0"
                >
                  {f}
                </Badge>
              ))}
            </div>
          </>
        ) : (
          !loading && (
            <div className="rounded-md border border-dashed border-border bg-muted/30 p-4 text-sm text-muted-foreground">
              <p className="font-medium">No stack curve for this slot.</p>
              <p className="mt-1">
                M4 only backfilled <span className="font-mono">TK</span> for{" "}
                <span className="font-mono">2023-01-01 → 2024-04-01</span>. For other
                areas or windows, run{" "}
                <span className="font-mono">
                  modal run apps/worker/modal_app.py::stack_backfill --start-iso ...
                  --end-iso ... --areas {area}
                </span>{" "}
                or wait for the daily{" "}
                <span className="font-mono">stack_run_daily</span> cron (06:30 JST).
              </p>
            </div>
          )
        )}
      </CardContent>
    </Card>
  );
}
