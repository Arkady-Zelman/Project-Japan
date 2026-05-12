/**
 * /api/demo-backtest
 *
 * Returns the most recent batch of demo (is_demo=true) backtests — one row
 * per strategy. Anonymous-readable — feeds the public /lab page.
 *
 * "Most recent batch" = all backtests with the same window_start as the
 * latest demo row, so the 4 strategies are aligned on the same date range.
 */

import { NextResponse } from "next/server";

import { createServerClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export async function GET() {
  const supabase = createServerClient();

  const { data: latest, error: lErr } = await supabase
    .from("backtests")
    .select("window_start, window_end")
    .eq("is_demo" as never, true)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (lErr) {
    return NextResponse.json({ error: lErr.message }, { status: 500 });
  }
  if (!latest) {
    return NextResponse.json(
      {
        error: "no demo backtests yet",
        note: "first daily run hasn't completed — check back after the next 06:30 JST cron.",
      },
      { status: 404 },
    );
  }

  const { data: backtests, error: bErr } = await supabase
    .from("backtests")
    .select(
      "*, asset:assets(name, area:areas(code, name_en), power_mw, energy_mwh)",
    )
    .eq("is_demo" as never, true)
    .eq("window_start", latest.window_start)
    .eq("window_end", latest.window_end)
    .order("strategy", { ascending: true });

  if (bErr) {
    return NextResponse.json({ error: bErr.message }, { status: 500 });
  }

  return NextResponse.json({
    window: { start: latest.window_start, end: latest.window_end },
    backtests: backtests ?? [],
  });
}
