/**
 * /workbench — public demo of the LSM storage valuer.
 *
 * Was an auth-gated, asset-CRUD-driven workbench. Now: read-only display of
 * the daily-refreshed demo BESS valuation (100 MWh / 50 MW Tokyo). The
 * underlying LSM engine, schema, and result component are all unchanged;
 * only the source of the `valuation_id` differs (cron-produced demo row
 * instead of user-triggered).
 */

import { createServerClient } from "@/lib/supabase/server";
import { PageHeader } from "@/components/ui/page-header";
import { ValuationResults } from "@/components/workbench/ValuationResults";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

async function fetchDemoValuationId(): Promise<string | null> {
  const supabase = createServerClient();
  const { data } = await supabase
    .from("valuations")
    .select("id")
    .eq("is_demo" as never, true)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  return (data?.id as string | undefined) ?? null;
}

export default async function WorkbenchPage() {
  const valuationId = await fetchDemoValuationId();

  return (
    <main className="mx-auto max-w-7xl px-6 py-12">
      <PageHeader
        title="Workbench"
        description={
          <>
            Daily Boogert &amp; de Jong Least-Squares Monte Carlo valuation of
            a 100 MWh / 50 MW Tokyo BESS against the latest VLSTM forecast
            paths. Refreshes automatically every morning at 06:30 JST after
            the day&rsquo;s ingest + stack build complete.
          </>
        }
      />
      {valuationId ? (
        <ValuationResults valuationId={valuationId} />
      ) : (
        <p className="mt-8 text-sm text-muted-foreground">
          The demo valuation hasn&rsquo;t run yet. The first cron firing
          after this deploy will populate it.
        </p>
      )}
    </main>
  );
}
