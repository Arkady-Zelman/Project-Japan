/**
 * /api/demo-valuation
 *
 * Returns the latest demo (is_demo=true) LSM valuation row plus its
 * per-slot decisions. Anonymous-readable — feeds the public /workbench page.
 */

import { NextResponse } from "next/server";

import { createServerClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export async function GET() {
  const supabase = createServerClient();

  const { data: vRow, error: vErr } = await supabase
    .from("valuations")
    .select("*, asset:assets(name, area:areas(code, name_en), power_mw, energy_mwh, round_trip_eff)")
    .eq("is_demo" as never, true)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (vErr) {
    return NextResponse.json({ error: vErr.message }, { status: 500 });
  }
  if (!vRow) {
    return NextResponse.json(
      {
        error: "no demo valuation yet",
        note: "first daily run hasn't completed — check back after the next 06:30 JST cron.",
      },
      { status: 404 },
    );
  }

  const { data: decisions } = await supabase
    .from("valuation_decisions")
    .select("*")
    .eq("valuation_id", vRow.id)
    .order("slot_start", { ascending: true });

  return NextResponse.json({
    valuation: vRow,
    decisions: decisions ?? [],
  });
}
