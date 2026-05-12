/**
 * /dashboard — Server Component shell.
 *
 * Fetches the compute_runs aggregates server-side then hands them to the
 * tabbed `DashboardClient` which owns the interactive map, regional refresh,
 * and chart lazy-loading.
 */

import { Suspense } from "react";

import { createServerClient } from "@/lib/supabase/server";
import { DashboardClient } from "@/components/dashboard/DashboardClient";
import type { DataSpan, LatestRun } from "@/components/dashboard/types";

import type { CronRun } from "@/components/dashboard/CronHealthStrip";

export const dynamic = "force-dynamic";

const INGEST_KINDS = [
  "ingest_jepx_prices",
  "ingest_demand",
  "ingest_generation_mix",
  "ingest_weather",
  "ingest_fx",
  "ingest_fuel_prices",
  "ingest_holidays",
] as const;

const MODEL_KINDS = [
  "regime_calibrate",
  "regime_infer",
  "regime_validate",
  "vlstm_train",
  "forecast_inference",
] as const;

const COMPUTE_KINDS = [
  "stack_build",
  "lsm_valuation",
  "backtest",
] as const;

const TABLE_SPANS: { kind: (typeof INGEST_KINDS)[number]; table: string; column: string }[] = [
  { kind: "ingest_jepx_prices", table: "jepx_spot_prices", column: "slot_start" },
  { kind: "ingest_demand", table: "demand_actuals", column: "slot_start" },
  { kind: "ingest_generation_mix", table: "generation_mix_actuals", column: "slot_start" },
  { kind: "ingest_weather", table: "weather_obs", column: "ts" },
  { kind: "ingest_fx", table: "fx_rates", column: "ts" },
  { kind: "ingest_fuel_prices", table: "fuel_prices", column: "ts" },
  { kind: "ingest_holidays", table: "jp_holidays", column: "date" },
];

const ALL_KINDS = [...INGEST_KINDS, ...MODEL_KINDS, ...COMPUTE_KINDS] as const;

async function fetchLatestRuns(): Promise<LatestRun[]> {
  const supa = createServerClient();
  const { data, error } = await supa
    .from("compute_runs")
    .select("kind, status, created_at, duration_ms, error, output")
    .in("kind", [...ALL_KINDS])
    .order("created_at", { ascending: false })
    .limit(500);
  if (error) {
    console.error("compute_runs fetch failed:", error);
    return [];
  }
  const seen = new Set<string>();
  const latest: LatestRun[] = [];
  for (const row of (data ?? []) as LatestRun[]) {
    if (seen.has(row.kind)) continue;
    seen.add(row.kind);
    latest.push(row);
  }
  return latest;
}

async function fetchDataSpans(): Promise<DataSpan[]> {
  const supa = createServerClient();
  type TableName = keyof import("@jepx/shared-types").Database["public"]["Tables"];
  const out: DataSpan[] = [];
  await Promise.all(
    TABLE_SPANS.map(async ({ kind, table, column }) => {
      const t = table as TableName;
      const [{ count }, { data: minData }, { data: maxData }] = await Promise.all([
        supa.from(t).select("*", { count: "exact", head: true }),
        supa.from(t).select(column).order(column, { ascending: true }).limit(1),
        supa.from(t).select(column).order(column, { ascending: false }).limit(1),
      ]);
      const minRow = (minData ?? [])[0] as Record<string, string> | undefined;
      const maxRow = (maxData ?? [])[0] as Record<string, string> | undefined;
      out.push({
        kind,
        table,
        min: minRow?.[column] ?? null,
        max: maxRow?.[column] ?? null,
        row_count: count ?? 0,
      });
    })
  );
  return out;
}

async function fetchRecentRuns(): Promise<CronRun[]> {
  const supa = createServerClient();
  const since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
  const { data, error } = await supa
    .from("compute_runs")
    .select("kind, status, created_at, error")
    .in("kind", [...ALL_KINDS])
    .gte("created_at", since)
    .order("created_at", { ascending: false })
    .limit(2000);
  if (error) {
    console.error("compute_runs (7d) fetch failed:", error);
    return [];
  }
  return (data ?? []) as CronRun[];
}

export default async function DashboardPage() {
  const [latestRuns, dataSpans, recentRuns] = await Promise.all([
    fetchLatestRuns(),
    fetchDataSpans(),
    fetchRecentRuns(),
  ]);

  return (
    <Suspense fallback={null}>
      <DashboardClient
        latestRuns={latestRuns}
        dataSpans={dataSpans}
        recentRuns={recentRuns}
      />
    </Suspense>
  );
}
