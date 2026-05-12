/**
 * /lab — public demo of the strategy backtest engine.
 *
 * Was an auth-gated form for picking an asset + window + strategies. Now:
 * read-only comparison of the latest daily 4-strategy backtest on the demo
 * BESS over the most recent 30 days of realised JEPX history. The
 * underlying engine and BacktestResults component are unchanged.
 */

import { createServerClient } from "@/lib/supabase/server";
import { PageHeader } from "@/components/ui/page-header";
import { BacktestResults } from "@/components/lab/BacktestResults";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

async function fetchDemoBacktestIds(): Promise<{
  ids: string[];
  window: { start: string; end: string } | null;
}> {
  const supabase = createServerClient();

  const { data: latest } = await supabase
    .from("backtests")
    .select("window_start, window_end")
    .eq("is_demo" as never, true)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (!latest) return { ids: [], window: null };

  const { data: rows } = await supabase
    .from("backtests")
    .select("id")
    .eq("is_demo" as never, true)
    .eq("window_start", latest.window_start)
    .eq("window_end", latest.window_end)
    .order("strategy", { ascending: true });

  return {
    ids: (rows ?? []).map((r) => r.id as string),
    window: {
      start: latest.window_start as string,
      end: latest.window_end as string,
    },
  };
}

export default async function LabPage() {
  const { ids, window } = await fetchDemoBacktestIds();

  const windowLabel = window
    ? `${window.start} → ${window.end}`
    : "(no demo run yet)";

  return (
    <main className="mx-auto max-w-7xl px-6 py-12">
      <PageHeader
        title="Strategy lab"
        description={
          <>
            Four dispatch strategies (naive spread, intrinsic, rolling
            intrinsic, LSM) replayed daily on realised JEPX history for the
            demo 100 MWh / 50 MW Tokyo BESS. Compare cumulative P&amp;L,
            Sharpe, and max drawdown after slippage.{" "}
            <span className="text-muted-foreground">Window: {windowLabel}</span>
          </>
        }
      />
      {ids.length > 0 ? (
        <BacktestResults backtestIds={ids} />
      ) : (
        <p className="mt-8 text-sm text-muted-foreground">
          The demo backtests haven&rsquo;t run yet. The first cron firing
          after this deploy will populate them.
        </p>
      )}
    </main>
  );
}
