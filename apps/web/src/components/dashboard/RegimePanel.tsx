"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

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

const SELECT_CLS =
  "w-full appearance-none rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring";

type Point = {
  slot_start: string;
  p_base: number;
  p_spike: number;
  p_drop: number;
  most_likely_regime: "base" | "spike" | "drop";
};

type RegimeResponse = {
  area: { id: string; code: string; name_en: string };
  model_version: string | null;
  points: Point[];
  note?: string;
};

const COLORS = {
  base: "#22c55e",   // green
  spike: "#dc2626",  // red
  drop: "#0ea5e9",   // blue
};

export function RegimePanel() {
  const [area, setArea] = useState<AreaCode>("TK");
  const [days, setDays] = useState<number>(7);
  const [data, setData] = useState<RegimeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(`/api/regime-states?area=${area}&days=${days}`)
      .then(async (r) => {
        const j = await r.json();
        if (!r.ok) throw new Error(j?.error?.toString() ?? r.statusText);
        return j as RegimeResponse;
      })
      .then((d) => setData(d))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [area, days]);

  const chartData = useMemo(() => {
    if (!data?.points) return [];
    return data.points.map((p) => ({
      ts: new Date(p.slot_start).getTime(),
      base: p.p_base,
      spike: p.p_spike,
      drop: p.p_drop,
    }));
  }, [data]);

  const latestRegime = data?.points?.length
    ? data.points[data.points.length - 1]?.most_likely_regime
    : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Section D — Regime panel</CardTitle>
        <CardDescription>
          Posterior probability of each regime ({" "}
          <span style={{ color: COLORS.base }}>base</span> /{" "}
          <span style={{ color: COLORS.spike }}>spike</span> /{" "}
          <span style={{ color: COLORS.drop }}>drop</span>) from the 3-regime
          MRS fitted on the residual <span className="font-mono">log(price/stack)</span>.
          Stacked area sums to 1 at every slot.
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
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Window (days)</label>
            <select
              className={SELECT_CLS}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              {[3, 7, 14, 30].map((d) => (
                <option key={d} value={d}>
                  Last {d} days
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Latest most-likely</label>
            <div className="rounded-md border border-input bg-background px-3 py-1.5 text-sm">
              {latestRegime ? (
                <span style={{ color: COLORS[latestRegime] }} className="font-medium">
                  {latestRegime.toUpperCase()}
                </span>
              ) : (
                "—"
              )}
              <span className="ml-2 text-xs text-muted-foreground">
                {data?.model_version ? `(${data.model_version})` : ""}
              </span>
            </div>
          </div>
        </div>

        <Separator />

        {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && <p className="text-sm text-red-600">Error: {error}</p>}
        {data?.note && <p className="text-sm text-muted-foreground">{data.note}</p>}

        {chartData.length > 0 ? (
          <div className="h-[280px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 8, right: 24, bottom: 24, left: 56 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  type="number"
                  dataKey="ts"
                  domain={["dataMin", "dataMax"]}
                  scale="time"
                  tickFormatter={(t) => {
                    const d = new Date(t as number);
                    return d.toLocaleDateString("ja-JP", {
                      month: "numeric",
                      day: "numeric",
                    });
                  }}
                  label={{
                    value: "Slot start (JST)",
                    position: "insideBottom",
                    offset: -10,
                    style: { textAnchor: "middle" },
                  }}
                />
                <YAxis
                  domain={[0, 1]}
                  tickFormatter={(v) => `${Math.round((v as number) * 100)}%`}
                  label={{
                    value: "Probability",
                    angle: -90,
                    position: "insideLeft",
                    offset: -38,
                    style: { textAnchor: "middle" },
                  }}
                />
                <ReTooltip
                  labelFormatter={(t) => new Date(t as number).toLocaleString("ja-JP")}
                  formatter={(value, name) => {
                    const v = typeof value === "number" ? value : Number(value);
                    return [
                      Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : "—",
                      String(name),
                    ];
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="base"
                  stackId="1"
                  stroke={COLORS.base}
                  fill={COLORS.base}
                  fillOpacity={0.7}
                  isAnimationActive={false}
                />
                <Area
                  type="monotone"
                  dataKey="drop"
                  stackId="1"
                  stroke={COLORS.drop}
                  fill={COLORS.drop}
                  fillOpacity={0.7}
                  isAnimationActive={false}
                />
                <Area
                  type="monotone"
                  dataKey="spike"
                  stackId="1"
                  stroke={COLORS.spike}
                  fill={COLORS.spike}
                  fillOpacity={0.7}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : (
          !loading && (
            <p className="text-sm text-muted-foreground">
              No regime states yet. Run{" "}
              <span className="font-mono">python -m regime.mrs_calibrate</span>{" "}
              or wait for the weekly{" "}
              <span className="font-mono">regime_calibrate_weekly</span> cron
              (Sun 03:00 JST).
            </p>
          )
        )}
      </CardContent>
    </Card>
  );
}
