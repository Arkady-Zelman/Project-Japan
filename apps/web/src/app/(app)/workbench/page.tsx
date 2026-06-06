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
import { ValuationResults } from "@/components/workbench/ValuationResults";
import { WorkbenchEmpty, WorkbenchHeader } from "@/components/workbench/WorkbenchHeader";

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
      <WorkbenchHeader />
      {valuationId ? <ValuationResults valuationId={valuationId} /> : <WorkbenchEmpty />}
    </main>
  );
}
