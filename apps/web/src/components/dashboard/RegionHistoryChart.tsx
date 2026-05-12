"use client";

/**
 * Historical line chart for a region (with optional comparison overlays).
 * Embedded inside the RegionDetail accordion on the Map tab.
 *
 * Metric is driven by the parent — the same toggle that drives the map.
 * Days are user-selectable (7 / 30 / 90). Other regions can be overlaid via
 * the toggle row beneath the chart.
 */

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts";

type Metric = "vre_share" | "balance_pct" | "price";

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

// Hand-picked palette with the primary area in saturated blue and the rest
// in muted distinct hues that read against the dark glass background.
const COLORS: Record<AreaCode, string> = {
  TK: "#3b82f6", // blue
  HK: "#22c55e", // emerald
  TH: "#f59e0b", // amber
  CB: "#a855f7", // purple
  HR: "#06b6d4", // cyan
  KS: "#ef4444", // red
  CG: "#84cc16", // lime
  SK: "#ec4899", // pink
  KY: "#eab308", // yellow
};

const METRIC_AXIS_LABEL: Record<Metric, string> = {
  vre_share: "VRE share",
  balance_pct: "Balance",
  price: "JEPX day-ahead",
};

const METRIC_UNIT: Record<Metric, string> = {
  vre_share: "%",
  balance_pct: "%",
  price: "¥/kWh",
};

type HistoryResponse = {
  metric: Metric;
  days: number;
  areas: string[];
  points: ({ day: string } & Record<string, number | null>)[];
};

const fmtDate = (d: string) => {
  const m = String(new Date(d).getUTCMonth() + 1).padStart(2, "0");
  const dd = String(new Date(d).getUTCDate()).padStart(2, "0");
  return `${m}-${dd}`;
};

const fmtValue = (v: number | null | undefined, m: Metric): string => {
  if (v == null || !Number.isFinite(v)) return "—";
  if (m === "vre_share") return `${(v * 100).toFixed(1)}%`;
  if (m === "balance_pct") return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  return `¥${v.toFixed(2)}`;
};

export function RegionHistoryChart({
  primary,
  metric,
}: {
  primary: AreaCode;
  metric: Metric;
}) {
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [overlays, setOverlays] = useState<Set<AreaCode>>(new Set());
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Active set = primary + overlays. Use a stable order: primary first, then
  // overlays in canonical AREAS order so colours / legend stay deterministic.
  const activeCodes: AreaCode[] = useMemo(() => {
    const set = new Set<AreaCode>([primary, ...Array.from(overlays)]);
    return AREAS.map((a) => a.code).filter((c) => set.has(c));
  }, [primary, overlays]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      areas: activeCodes.join(","),
      metric,
      days: String(days),
    });
    fetch(`/api/region-history?${params}`)
      .then(async (r) => {
        const j = await r.json();
        if (!r.ok) throw new Error(j?.error?.toString() ?? r.statusText);
        return j as HistoryResponse;
      })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeCodes, metric, days]);

  const toggleOverlay = (code: AreaCode) => {
    if (code === primary) return; // primary always on
    setOverlays((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const yTickFormatter = (v: number) => {
    if (metric === "vre_share") return `${Math.round(v * 100)}%`;
    if (metric === "balance_pct") return `${Math.round(v * 100)}%`;
    return `¥${v.toFixed(0)}`;
  };

  return (
    <div className="mt-6 rounded-xl border border-foreground/5 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="text-sm font-medium">
            {METRIC_AXIS_LABEL[metric]} — last {days} days
          </h4>
          <p className="text-xs text-muted-foreground">
            Daily average. Click area codes below to overlay.
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-md bg-muted/40 p-1 text-xs">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d as 7 | 30 | 90)}
              className={
                "rounded px-2 py-1 font-medium transition " +
                (days === d
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground")
              }
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      <div className="h-[280px] w-full">
        {loading && !data && (
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
            Loading…
          </div>
        )}
        {error && (
          <p className="text-xs text-red-500">{error}</p>
        )}
        {data && data.points.length === 0 && !loading && (
          <p className="flex h-full items-center justify-center text-xs text-muted-foreground">
            No data in this window.
          </p>
        )}
        {data && data.points.length > 0 && (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.points} margin={{ top: 8, right: 16, bottom: 48, left: 56 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
              <XAxis
                dataKey="day"
                tick={{ fontSize: 10, fill: "#a3a3a3" }}
                angle={-90}
                textAnchor="end"
                height={48}
                tickFormatter={fmtDate}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "#a3a3a3" }}
                tickFormatter={yTickFormatter}
                label={{
                  value: `${METRIC_AXIS_LABEL[metric]} (${METRIC_UNIT[metric]})`,
                  angle: -90,
                  position: "insideLeft",
                  offset: -38,
                  style: { textAnchor: "middle", fontSize: 11, fill: "#a3a3a3" },
                }}
              />
              <ReTooltip
                labelFormatter={(d) => `${d} UTC`}
                formatter={(value, name) => {
                  const n = typeof value === "number" ? value : Number(value);
                  return [fmtValue(n, metric), String(name)];
                }}
              />
              <Legend
                verticalAlign="top"
                align="center"
                height={28}
                wrapperStyle={{ paddingBottom: 8, fontSize: 11 }}
              />
              {activeCodes.map((code) => (
                <Line
                  key={code}
                  type="monotone"
                  dataKey={code}
                  stroke={COLORS[code]}
                  strokeWidth={code === primary ? 2.5 : 1.5}
                  dot={false}
                  isAnimationActive={false}
                  connectNulls
                  name={code}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
        {AREAS.map((a) => {
          const isPrimary = a.code === primary;
          const isOn = isPrimary || overlays.has(a.code);
          return (
            <button
              key={a.code}
              type="button"
              onClick={() => toggleOverlay(a.code)}
              disabled={isPrimary}
              title={`${a.name} (${a.code})${isPrimary ? " — primary, always shown" : ""}`}
              className={
                "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 transition " +
                (isOn
                  ? "border-foreground/30 text-foreground"
                  : "border-foreground/10 text-muted-foreground hover:text-foreground hover:border-foreground/20") +
                (isPrimary ? " cursor-default opacity-80" : "")
              }
            >
              <span
                className="inline-block size-2 rounded-full"
                style={{ background: isOn ? COLORS[a.code] : "transparent", border: !isOn ? `1px solid ${COLORS[a.code]}` : undefined }}
              />
              <span className="font-mono">{a.code}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
