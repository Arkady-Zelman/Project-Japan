/**
 * /dashboard — M3 ingest-status panel.
 *
 * Server Component: queries `compute_runs` and the per-target tables on each
 * page load. Hands the snapshot to a Client Component that subscribes to
 * Realtime and re-renders as new ingest runs land.
 */

import { createServerClient } from "@/lib/supabase/server";
import { IngestStatusTable } from "@/components/dashboard/IngestStatusTable";

export const dynamic = "force-dynamic";

const EXPECTED_SOURCES = [
  "ingest_jepx_prices",
  "ingest_demand",
  "ingest_generation_mix",
  "ingest_weather",
  "ingest_fx",
  "ingest_holidays",
] as const;

const TABLE_SPANS: { kind: (typeof EXPECTED_SOURCES)[number]; table: string; column: string }[] = [
  { kind: "ingest_jepx_prices", table: "jepx_spot_prices", column: "slot_start" },
  { kind: "ingest_demand", table: "demand_actuals", column: "slot_start" },
  { kind: "ingest_generation_mix", table: "generation_mix_actuals", column: "slot_start" },
  { kind: "ingest_weather", table: "weather_obs", column: "ts" },
  { kind: "ingest_fx", table: "fx_rates", column: "ts" },
  { kind: "ingest_holidays", table: "jp_holidays", column: "date" },
];

export type LatestRun = {
  kind: string;
  status: string;
  created_at: string;
  duration_ms: number | null;
  error: string | null;
  output: Record<string, unknown> | null;
};

export type DataSpan = {
  kind: string;
  table: string;
  min: string | null;
  max: string | null;
  row_count: number;
};

async function fetchLatestRuns(): Promise<LatestRun[]> {
  const supa = createServerClient();
  const { data, error } = await supa
    .from("compute_runs")
    .select("kind, status, created_at, duration_ms, error, output")
    .like("kind", "ingest_%")
    .order("created_at", { ascending: false })
    .limit(100);
  if (error) {
    console.error("compute_runs fetch failed:", error);
    return [];
  }
  // Dedupe to one row per kind (latest first).
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
  // Cast through `keyof Database["public"]["Tables"]` so the dynamic table-name
  // loop type-checks against the generated client. The TABLE_SPANS list is
  // hardcoded above so the cast is safe — every entry is a real table.
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

export default async function DashboardPage() {
  const [latestRuns, dataSpans] = await Promise.all([fetchLatestRuns(), fetchDataSpans()]);

  return (
    <main className="mx-auto max-w-6xl px-6 py-12">
      <header className="mb-10">
        <h1 className="text-3xl font-semibold tracking-tight">Ingest health</h1>
        <p className="mt-2 text-sm text-neutral-500">
          Per-source view of the daily ingest pipeline. Updates live via Supabase Realtime
          when new <code className="rounded bg-neutral-100 px-1 py-0.5 text-xs dark:bg-neutral-900">compute_runs</code> rows land.
        </p>
      </header>

      <IngestStatusTable
        expectedSources={[...EXPECTED_SOURCES]}
        initialRuns={latestRuns}
        dataSpans={dataSpans}
      />
    </main>
  );
}
