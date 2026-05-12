"use client";

/**
 * Japan regional map — 9 JEPX utility regions rendered as a real cartographic
 * SVG (pre-projected by apps/web/scripts/build-japan-paths.mjs).
 *
 * Behaviour:
 *  - Fill encodes a chosen metric (default: VRE share).
 *  - Hover → stroke highlight + native tooltip via title.
 *  - Click → notifies parent which region is selected (parent renders the
 *    inline RegionDetail accordion below).
 *  - Auto-refreshes via `useRealtimeRegionalBalance` (30-min heartbeat +
 *    Realtime on demand_actuals INSERT).
 */

import { useMemo, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useRealtimeRegionalBalance } from "@/hooks/useRealtimeRegionalBalance";
import {
  REGION_PATHS,
  VIEW_BOX,
  type RegionCode,
} from "@/lib/japan-region-paths";

import type { RegionalBalance } from "@/app/api/regional-balance/route";

type Metric = "vre_share" | "balance_pct" | "price";

const METRICS: { id: Metric; label: string; help: string }[] = [
  { id: "vre_share", label: "VRE share", help: "Share of demand met by solar, wind and hydro" },
  { id: "balance_pct", label: "Balance", help: "(Generation − Demand) / Demand" },
  { id: "price", label: "JEPX price", help: "Day-ahead clearing, ¥/kWh" },
];

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function lerpRgb(c1: [number, number, number], c2: [number, number, number], t: number) {
  const r = Math.round(lerp(c1[0], c2[0], t));
  const g = Math.round(lerp(c1[1], c2[1], t));
  const b = Math.round(lerp(c1[2], c2[2], t));
  return `rgb(${r},${g},${b})`;
}

// Sequential green scale: pale grey → emerald.
const GREEN_LO: [number, number, number] = [241, 245, 249]; // slate-100
const GREEN_HI: [number, number, number] = [16, 185, 129]; // emerald-500

// Diverging red ↔ neutral ↔ green for balance.
const RED: [number, number, number] = [220, 38, 38]; // red-600
const NEUTRAL: [number, number, number] = [229, 231, 235]; // gray-200
const GREEN: [number, number, number] = [16, 185, 129]; // emerald-500

// Sequential blue scale for price (low = pale, high = deep).
const BLUE_LO: [number, number, number] = [241, 245, 249];
const BLUE_HI: [number, number, number] = [29, 78, 216]; // blue-700

function valueForMetric(r: RegionalBalance | undefined, m: Metric): number | null {
  if (!r) return null;
  if (m === "vre_share") return r.vre_share;
  if (m === "balance_pct") return r.balance_pct;
  if (m === "price") return r.price_jpy_kwh;
  return null;
}

function colorFor(v: number | null, m: Metric, vMin: number, vMax: number): string {
  if (v == null || !Number.isFinite(v)) return "rgb(243,244,246)"; // gray-100
  if (m === "vre_share") {
    const t = Math.max(0, Math.min(1, v));
    return lerpRgb(GREEN_LO, GREEN_HI, t);
  }
  if (m === "balance_pct") {
    const range = Math.max(Math.abs(vMin), Math.abs(vMax), 0.05);
    const t = Math.max(-1, Math.min(1, v / range));
    if (t >= 0) return lerpRgb(NEUTRAL, GREEN, t);
    return lerpRgb(NEUTRAL, RED, -t);
  }
  // price — sequential
  const range = vMax - vMin || 1;
  const t = Math.max(0, Math.min(1, (v - vMin) / range));
  return lerpRgb(BLUE_LO, BLUE_HI, t);
}

function formatValue(v: number | null, m: Metric): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (m === "vre_share") return `${(v * 100).toFixed(0)}%`;
  if (m === "balance_pct") return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(0)}%`;
  if (m === "price") return `¥${v.toFixed(2)}`;
  return "—";
}

export function JapanRegionalMap({
  selected,
  onSelect,
}: {
  selected: RegionCode | null;
  onSelect: (code: RegionCode | null) => void;
}) {
  const { rows, slotStart, loading, error } = useRealtimeRegionalBalance();
  const [metric, setMetric] = useState<Metric>("vre_share");
  const [hovered, setHovered] = useState<RegionCode | null>(null);

  const rowsByCode = useMemo(() => {
    const m = new Map<string, RegionalBalance>();
    for (const r of rows) m.set(r.code, r);
    return m;
  }, [rows]);

  const { vMin, vMax } = useMemo(() => {
    let lo = Infinity, hi = -Infinity;
    for (const r of rows) {
      const v = valueForMetric(r, metric);
      if (v != null && Number.isFinite(v)) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
    return { vMin: Number.isFinite(lo) ? lo : 0, vMax: Number.isFinite(hi) ? hi : 1 };
  }, [rows, metric]);

  if (loading && rows.length === 0) {
    return <Skeleton className="h-[560px] w-full" />;
  }

  return (
    <div className="rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-medium">Regional snapshot</h2>
          <p className="text-xs text-muted-foreground">
            {slotStart ? `Slot ${new Date(slotStart).toISOString().slice(0, 16).replace("T", " ")} UTC` : "—"}
            {" · "}9 JEPX utility regions
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-md bg-muted p-1">
          {METRICS.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setMetric(m.id)}
              title={m.help}
              className={`rounded px-2.5 py-1 text-xs font-medium transition ${
                metric === m.id
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_260px]">
        <div className="relative w-full">
          <svg
            viewBox={`${VIEW_BOX.x} ${VIEW_BOX.y} ${VIEW_BOX.w} ${VIEW_BOX.h}`}
            className="mx-auto block h-auto w-full max-w-[820px]"
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label="Japan utility regions"
          >
            <g>
              {REGION_PATHS.map((p) => {
                const row = rowsByCode.get(p.code);
                const value = valueForMetric(row, metric);
                const fill = colorFor(value, metric, vMin, vMax);
                const isSelected = selected === p.code;
                const isHovered = hovered === p.code;
                return (
                  <path
                    key={p.code}
                    d={p.d}
                    fill={fill}
                    stroke={isSelected ? "#1d4ed8" : isHovered ? "#0f172a" : "#cbd5e1"}
                    strokeWidth={isSelected ? 2 : isHovered ? 1.5 : 0.75}
                    onMouseEnter={() => setHovered(p.code)}
                    onMouseLeave={() => setHovered((h) => (h === p.code ? null : h))}
                    onClick={() => onSelect(isSelected ? null : p.code)}
                    style={{ cursor: "pointer", transition: "stroke 120ms, stroke-width 120ms" }}
                  >
                    <title>{`${p.name} — ${formatValue(value, metric)}`}</title>
                  </path>
                );
              })}
            </g>
          </svg>
        </div>

        {/* Region list (also serves as the mobile fallback when the SVG is small) */}
        <ol className="space-y-1 text-sm">
          {REGION_PATHS.map((p) => {
            const row = rowsByCode.get(p.code);
            const value = valueForMetric(row, metric);
            const fill = colorFor(value, metric, vMin, vMax);
            const isSelected = selected === p.code;
            return (
              <li key={p.code}>
                <button
                  type="button"
                  onClick={() => onSelect(isSelected ? null : p.code)}
                  onMouseEnter={() => setHovered(p.code)}
                  onMouseLeave={() => setHovered((h) => (h === p.code ? null : h))}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition hover:bg-muted ${
                    isSelected ? "bg-muted ring-1 ring-foreground/10" : ""
                  }`}
                >
                  <span
                    className="inline-block size-3 rounded-sm ring-1 ring-foreground/10"
                    style={{ backgroundColor: fill }}
                  />
                  <span className="flex-1 truncate font-medium">{p.name}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {formatValue(value, metric)}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>

      <Legend metric={metric} vMin={vMin} vMax={vMax} />
    </div>
  );
}

function Legend({ metric, vMin, vMax }: { metric: Metric; vMin: number; vMax: number }) {
  const stops =
    metric === "balance_pct"
      ? [
          { c: lerpRgb(NEUTRAL, RED, 1), label: "Deficit" },
          { c: lerpRgb(NEUTRAL, NEUTRAL, 0), label: "Balanced" },
          { c: lerpRgb(NEUTRAL, GREEN, 1), label: "Surplus" },
        ]
      : metric === "vre_share"
        ? [
            { c: lerpRgb(GREEN_LO, GREEN_LO, 0), label: `${Math.round(vMin * 100)}%` },
            { c: lerpRgb(GREEN_LO, GREEN_HI, 0.5), label: `${Math.round(((vMin + vMax) / 2) * 100)}%` },
            { c: lerpRgb(GREEN_LO, GREEN_HI, 1), label: `${Math.round(vMax * 100)}%` },
          ]
        : [
            { c: lerpRgb(BLUE_LO, BLUE_LO, 0), label: `¥${vMin.toFixed(1)}` },
            { c: lerpRgb(BLUE_LO, BLUE_HI, 0.5), label: `¥${((vMin + vMax) / 2).toFixed(1)}` },
            { c: lerpRgb(BLUE_LO, BLUE_HI, 1), label: `¥${vMax.toFixed(1)}` },
          ];
  return (
    <div className="mt-4 flex items-center gap-3 text-xs text-muted-foreground">
      <span>Legend</span>
      <div className="flex items-center gap-1.5">
        {stops.map((s, i) => (
          <span key={i} className="inline-flex items-center gap-1">
            <span
              className="inline-block size-3 rounded-sm ring-1 ring-foreground/10"
              style={{ backgroundColor: s.c }}
            />
            <span>{s.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
