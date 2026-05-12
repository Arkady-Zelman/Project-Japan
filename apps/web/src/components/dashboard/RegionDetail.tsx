"use client";

/**
 * Region detail panel shown beneath the JapanRegionalMap when a region is
 * selected. Reuses regional balance fetched by the parent.
 */

import Link from "next/link";
import { useMemo } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip as ReTooltip } from "recharts";

import { MetricCard } from "@/components/ui/metric-card";
import { fuelColor } from "@/lib/fuel-colors";

import type { RegionalBalance } from "@/app/api/regional-balance/route";

export function RegionDetail({
  row,
  onClose,
}: {
  row: RegionalBalance | null;
  onClose: () => void;
}) {
  const pieData = useMemo(() => {
    if (!row) return [];
    return row.generation
      .filter((g) => g.output_mw > 0)
      .map((g) => ({ name: g.fuel_code, value: g.output_mw }));
  }, [row]);

  if (!row) return null;

  const balanceTone =
    row.balance_pct == null
      ? "neutral"
      : row.balance_pct > 0.05
        ? "positive"
        : row.balance_pct < -0.05
          ? "negative"
          : "neutral";

  return (
    <section className="mt-6 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <header className="mb-4 flex items-baseline justify-between">
        <div>
          <h3 className="text-xl font-semibold tracking-tight">{row.name}</h3>
          <p className="text-xs text-muted-foreground">
            Area <span className="font-mono">{row.code}</span> · slot{" "}
            {new Date(row.slot_start).toISOString().slice(0, 16).replace("T", " ")} UTC
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-foreground/10 px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
        >
          Close
        </button>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricCard
          label="Demand"
          value={row.demand_mw != null ? Math.round(row.demand_mw).toLocaleString() : "—"}
          unit="MW"
        />
        <MetricCard
          label="Generation"
          value={Math.round(row.total_gen_mw).toLocaleString()}
          unit="MW"
        />
        <MetricCard
          label="Balance"
          value={
            row.balance_pct != null
              ? `${row.balance_pct >= 0 ? "+" : ""}${(row.balance_pct * 100).toFixed(1)}`
              : "—"
          }
          unit="%"
          tone={balanceTone as "positive" | "negative" | "neutral"}
        />
        <MetricCard
          label="JEPX day-ahead"
          value={row.price_jpy_kwh != null ? row.price_jpy_kwh.toFixed(2) : "—"}
          unit="¥/kWh"
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-[260px_1fr]">
        <div className="h-[220px]">
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  innerRadius={48}
                  outerRadius={90}
                  paddingAngle={1}
                  dataKey="value"
                  isAnimationActive={false}
                >
                  {pieData.map((d) => (
                    <Cell key={d.name} fill={fuelColor(d.name)} />
                  ))}
                </Pie>
                <ReTooltip
                  formatter={(v, name) => {
                    const n = typeof v === "number" ? v : Number(v as string);
                    if (!Number.isFinite(n)) return ["—", String(name)];
                    return [`${Math.round(n).toLocaleString()} MW`, String(name)];
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="flex h-full items-center justify-center text-sm text-muted-foreground">
              No generation breakdown for this slot.
            </p>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="py-1.5 pr-3 font-medium">Fuel</th>
                <th className="py-1.5 pr-3 font-medium text-right">MW</th>
                <th className="py-1.5 font-medium text-right">Share</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-foreground/5">
              {row.generation
                .slice()
                .sort((a, b) => b.output_mw - a.output_mw)
                .map((g) => {
                  const share = row.total_gen_mw > 0 ? g.output_mw / row.total_gen_mw : 0;
                  return (
                    <tr key={g.fuel_code}>
                      <td className="py-1.5 pr-3">
                        <span className="inline-flex items-center gap-2">
                          <span
                            className="inline-block size-2.5 rounded-sm"
                            style={{ backgroundColor: fuelColor(g.fuel_code) }}
                          />
                          <span className="font-mono text-xs">{g.fuel_code}</span>
                        </span>
                      </td>
                      <td className="py-1.5 pr-3 text-right tabular-nums">
                        {Math.round(g.output_mw).toLocaleString()}
                      </td>
                      <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                        {(share * 100).toFixed(1)}%
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </div>

      <footer className="mt-4 border-t border-foreground/5 pt-3 text-xs text-muted-foreground">
        <Link
          href={`/dashboard?tab=stack&area=${row.code}`}
          className="font-medium text-foreground hover:underline"
        >
          See stack curve →
        </Link>
      </footer>
    </section>
  );
}
