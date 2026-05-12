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

/**
 * Visual centroid of an SVG path. Splits on M/m, finds the sub-path with
 * the biggest bounding box, and averages its vertex coordinates — a better
 * label anchor than the bbox-centroid for irregular shapes like Japan's
 * regions (Hokkaido, Kyushu have many islands; we want the label on the
 * main mass, not floating between sub-paths).
 */
function bboxFromPath(d: string): { cx: number; cy: number } {
  const subs: string[] = [];
  let cur = "";
  for (let i = 0; i < d.length; i++) {
    const ch = d[i] ?? "";
    if ((ch === "M" || ch === "m") && cur.length) {
      subs.push(cur);
      cur = ch;
    } else {
      cur += ch;
    }
  }
  if (cur.length) subs.push(cur);

  let best: { cx: number; cy: number; area: number } | null = null;
  for (const s of subs) {
    const nums = s.match(/-?\d+(?:\.\d+)?/g);
    if (!nums || nums.length < 4) continue;
    let xMin = Infinity;
    let yMin = Infinity;
    let xMax = -Infinity;
    let yMax = -Infinity;
    let sumX = 0;
    let sumY = 0;
    let n = 0;
    for (let i = 0; i + 1 < nums.length; i += 2) {
      const x = +(nums[i] ?? "0");
      const y = +(nums[i + 1] ?? "0");
      if (x < xMin) xMin = x;
      if (x > xMax) xMax = x;
      if (y < yMin) yMin = y;
      if (y > yMax) yMax = y;
      sumX += x;
      sumY += y;
      n++;
    }
    if (n === 0) continue;
    const area = (xMax - xMin) * (yMax - yMin);
    if (!best || area > best.area) {
      best = { cx: sumX / n, cy: sumY / n, area };
    }
  }
  return best ?? { cx: 400, cy: 400 };
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

  // Largest-sub-path centroid per region — drives the on-map label position.
  const centroids = useMemo(() => {
    const m = new Map<string, { cx: number; cy: number }>();
    for (const p of REGION_PATHS) m.set(p.code, bboxFromPath(p.d));
    return m;
  }, []);

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
    <div className="glass p-4">
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
            viewBox="150 50 520 500"
            preserveAspectRatio="xMidYMid meet"
            className="mx-auto block h-auto w-full"
            style={{ maxHeight: 540 }}
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

            {/* Region code + value labels at the largest-sub-path centroid
                of each region — keeps the label on the visible mass even
                for fragmented shapes like Hokkaido and Kyushu. */}
            <g style={{ pointerEvents: "none" }}>
              {REGION_PATHS.map((p) => {
                const c = centroids.get(p.code);
                if (!c) return null;
                const row = rowsByCode.get(p.code);
                const value = valueForMetric(row, metric);
                const isSelected = selected === p.code;
                return (
                  <g key={p.code + "_lbl"} transform={`translate(${c.cx}, ${c.cy})`}>
                    <text
                      textAnchor="middle"
                      y="-3"
                      fontSize="16"
                      fontWeight="700"
                      fill={isSelected ? "#f8fafc" : "#0b1220"}
                      style={{
                        paintOrder: "stroke",
                        stroke: "rgba(255,255,255,0.9)",
                        strokeWidth: isSelected ? 0 : 3,
                        strokeLinejoin: "round",
                      }}
                    >
                      {p.code}
                    </text>
                    <text
                      textAnchor="middle"
                      y="13"
                      fontSize="13"
                      fontWeight="600"
                      fill={isSelected ? "#f8fafc" : "#0b1220"}
                      style={{
                        paintOrder: "stroke",
                        stroke: "rgba(255,255,255,0.9)",
                        strokeWidth: isSelected ? 0 : 3,
                        strokeLinejoin: "round",
                      }}
                    >
                      {formatValue(value, metric)}
                    </text>
                  </g>
                );
              })}
            </g>
          </svg>

          {/* Okinawa inset — bottom-left of the map area. Reuses the KY
              path with a viewBox cropped to the Ryukyu archipelago; click
              triggers the same onSelect("KY") as the main map. */}
          {(() => {
            const ky = REGION_PATHS.find((r) => r.code === "KY");
            if (!ky) return null;
            const row = rowsByCode.get("KY");
            const value = valueForMetric(row, metric);
            const fill = colorFor(value, metric, vMin, vMax);
            const isSelected = selected === "KY";
            return (
              <div
                onClick={() => onSelect(isSelected ? null : "KY")}
                title="Okinawa (part of Kyushu / KY)"
                className="absolute bottom-1 left-1 w-[156px] cursor-pointer rounded-[10px] bg-[linear-gradient(180deg,rgba(255,255,255,0.10)_0%,rgba(255,255,255,0.03)_40%,transparent_70%),rgba(28,30,38,0.45)] px-2 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.16),inset_0_0_0_1px_rgba(255,255,255,0.10)] backdrop-blur-[20px] backdrop-saturate-[1.4]"
              >
                <div className="mb-0.5 flex items-baseline justify-between">
                  <span className="text-[9.5px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                    Okinawa
                  </span>
                  <span className="text-[10px] text-muted-foreground">part of KY</span>
                </div>
                <svg
                  viewBox="115 645 130 85"
                  preserveAspectRatio="xMidYMid meet"
                  className="block h-[78px] w-full"
                  aria-label="Okinawa islands"
                >
                  <path
                    d={ky.d}
                    fill={fill}
                    stroke={isSelected ? "#1d4ed8" : "#cbd5e1"}
                    strokeWidth={isSelected ? 1 : 0.4}
                  />
                </svg>
              </div>
            );
          })()}
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
