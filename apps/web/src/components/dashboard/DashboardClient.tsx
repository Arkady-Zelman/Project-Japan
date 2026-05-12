"use client";

/**
 * Tab-bar shell for /dashboard. Holds the Map (default) and lazy-loads the
 * remaining heavy chart panels (Forecast / Stack / Regime / Health) only on
 * tab activation. URL state in `?tab=...&area=...` so deep links work.
 *
 * The hero metric strip + Map tab both consume `useRealtimeRegionalBalance`
 * for system-wide and per-region data, so 30-minute refresh + Realtime apply
 * across the page.
 */

import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { JapanRegionalMap } from "@/components/dashboard/JapanRegionalMap";
import { RegionDetail } from "@/components/dashboard/RegionDetail";
import { StrategyTab } from "@/components/dashboard/StrategyTab";
import { ComputeRunsTable } from "@/components/dashboard/ComputeRunsTable";
import {
  CronHealthStrip,
  type CronRun,
} from "@/components/dashboard/CronHealthStrip";
import { MetricCard } from "@/components/ui/metric-card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { TabBar, type TabBarItem } from "@/components/ui/tab-bar";
import { useRealtimeRegionalBalance } from "@/hooks/useRealtimeRegionalBalance";
import type { RegionCode } from "@/lib/japan-region-paths";

import type { DataSpan, LatestRun } from "@/components/dashboard/types";

const ForecastPanel = dynamic(
  () => import("@/components/dashboard/ForecastPanel").then((m) => m.ForecastPanel),
  { ssr: false, loading: () => <Skeleton className="h-[420px] w-full" /> },
);
const StackInspector = dynamic(
  () => import("@/components/dashboard/StackInspector").then((m) => m.StackInspector),
  { ssr: false, loading: () => <Skeleton className="h-[500px] w-full" /> },
);
const RegimePanel = dynamic(
  () => import("@/components/dashboard/RegimePanel").then((m) => m.RegimePanel),
  { ssr: false, loading: () => <Skeleton className="h-[360px] w-full" /> },
);

type TabId = "map" | "strategy" | "forecast" | "stack" | "regime" | "health";

const TABS: ReadonlyArray<TabBarItem<TabId>> = [
  { value: "map", label: "Map" },
  { value: "strategy", label: "Strategy" },
  { value: "forecast", label: "Forecast" },
  { value: "stack", label: "Stack" },
  { value: "regime", label: "Regime" },
  { value: "health", label: "Health" },
];

const INGEST_KINDS = [
  "ingest_jepx_prices",
  "ingest_demand",
  "ingest_generation_mix",
  "ingest_weather",
  "ingest_fx",
  "ingest_fuel_prices",
  "ingest_holidays",
];
const MODEL_KINDS = [
  "regime_calibrate",
  "regime_infer",
  "regime_validate",
  "vlstm_train",
  "forecast_inference",
];
const COMPUTE_KINDS = ["stack_build", "lsm_valuation", "backtest"];
const ALL_KINDS = [...INGEST_KINDS, ...MODEL_KINDS, ...COMPUTE_KINDS];

export function DashboardClient({
  latestRuns,
  dataSpans,
  recentRuns,
}: {
  latestRuns: LatestRun[];
  dataSpans: DataSpan[];
  recentRuns: CronRun[];
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const tab = (searchParams.get("tab") ?? "map") as TabId;
  const areaParam = searchParams.get("area");
  const [selectedRegion, setSelectedRegion] = useState<RegionCode | null>(
    (areaParam as RegionCode | null) ?? null,
  );

  const { rows, slotStart, loading, error, refresh, fetchedAt } = useRealtimeRegionalBalance();

  const systemTotals = useMemo(() => {
    let totalDemand = 0;
    let totalGen = 0;
    let totalVre = 0;
    let tokyoPrice: number | null = null;
    for (const r of rows) {
      if (r.demand_mw != null) totalDemand += r.demand_mw;
      totalGen += r.total_gen_mw;
      totalVre += r.vre_share * r.total_gen_mw;
      if (r.code === "TK") tokyoPrice = r.price_jpy_kwh;
    }
    const sysVreShare = totalGen > 0 ? totalVre / totalGen : 0;
    return { totalDemand, totalGen, sysVreShare, tokyoPrice };
  }, [rows]);

  const setTab = useCallback(
    (next: TabId) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", next);
      router.replace(`/dashboard?${params.toString()}`);
    },
    [router, searchParams],
  );

  const setRegion = useCallback(
    (next: RegionCode | null) => {
      setSelectedRegion(next);
      const params = new URLSearchParams(searchParams.toString());
      if (next) params.set("area", next);
      else params.delete("area");
      router.replace(`/dashboard?${params.toString()}`);
    },
    [router, searchParams],
  );

  const selectedRow = useMemo(
    () => rows.find((r) => r.code === selectedRegion) ?? null,
    [rows, selectedRegion],
  );

  return (
    <main className="mx-auto w-full max-w-[1600px] px-6 py-10">
      <PageHeader
        title="Japan power dashboard"
        description="Half-hourly snapshots of demand, generation mix, and JEPX clearing across the 9 utility regions. Forecasts, stack model, and pipeline health under the tabs."
        actions={
          <>
            <span className="text-xs text-muted-foreground">
              {fetchedAt
                ? `Updated ${fetchedAt.toISOString().slice(11, 19)} UTC`
                : "—"}
            </span>
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              className="inline-flex items-center gap-1 rounded-md border border-foreground/10 px-2 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
            >
              <span className={loading ? "inline-block animate-spin" : "inline-block"}>↻</span>
              <span>Refresh</span>
            </button>
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
                error
                  ? "bg-red-500/10 text-red-500"
                  : loading
                    ? "bg-amber-500/10 text-amber-500"
                    : rows.length === 0
                      ? "bg-muted text-muted-foreground"
                      : "bg-emerald-500/10 text-emerald-500"
              }`}
            >
              <span
                className={`inline-block size-1.5 rounded-full ${
                  error
                    ? "bg-red-500"
                    : loading
                      ? "bg-amber-500"
                      : rows.length === 0
                        ? "bg-muted-foreground"
                        : "bg-emerald-500"
                }`}
              />
              {error ? "Error" : loading ? "Syncing" : rows.length === 0 ? "No data" : "Live"}
            </span>
          </>
        }
        metrics={
          <>
            <MetricCard
              label="System demand"
              value={systemTotals.totalDemand > 0 ? Math.round(systemTotals.totalDemand).toLocaleString() : "—"}
              unit="MW"
              hint={slotStart ? new Date(slotStart).toISOString().slice(0, 16).replace("T", " ") + " UTC" : undefined}
            />
            <MetricCard
              label="System generation"
              value={systemTotals.totalGen > 0 ? Math.round(systemTotals.totalGen).toLocaleString() : "—"}
              unit="MW"
            />
            <MetricCard
              label="System VRE share"
              value={(systemTotals.sysVreShare * 100).toFixed(0)}
              unit="%"
              tone="positive"
            />
            <MetricCard
              label="Tokyo JEPX"
              value={systemTotals.tokyoPrice != null ? systemTotals.tokyoPrice.toFixed(2) : "—"}
              unit="¥/kWh"
            />
          </>
        }
      />

      {error && (
        <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2 text-sm text-red-500">
          Regional balance fetch failed: {error}
        </div>
      )}

      <TabBar value={tab} onValueChange={setTab} items={TABS}>
        {(active) => (
          <>
            {active === "map" && (
              <div>
                <JapanRegionalMap selected={selectedRegion} onSelect={setRegion} />
                <RegionDetail row={selectedRow} onClose={() => setRegion(null)} />
              </div>
            )}
            {active === "strategy" && <StrategyTab />}
            {active === "forecast" && <ForecastPanel />}
            {active === "stack" && <StackInspector />}
            {active === "regime" && <RegimePanel />}
            {active === "health" && (
              <div className="space-y-6">
                <CronHealthStrip runs={recentRuns} kinds={ALL_KINDS} />
                <ComputeRunsTable
                  title="Ingest"
                  description="Daily ingest pipeline: market, demand, generation mix, weather, FX, fuel, holidays."
                  kinds={INGEST_KINDS}
                  initialRuns={latestRuns}
                  dataSpans={dataSpans}
                />
                <ComputeRunsTable
                  title="Models"
                  description="Regime calibration, VLSTM training, twice-daily forecast inference."
                  kinds={MODEL_KINDS}
                  initialRuns={latestRuns}
                />
                <ComputeRunsTable
                  title="Compute"
                  description="Stack build, on-demand LSM valuations, strategy backtests."
                  kinds={COMPUTE_KINDS}
                  initialRuns={latestRuns}
                />
              </div>
            )}
          </>
        )}
      </TabBar>
    </main>
  );
}
