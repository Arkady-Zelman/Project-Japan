/**
 * /api/valuation-decisions?valuation_id=X
 *
 * Returns per-slot decision rows (M10C L7 decision heatmap).
 * Joins valuation_decisions with regime_states via the asset's area_id.
 */

import { NextResponse } from "next/server";

import { createServerClient, createSessionClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

type DecisionRow = {
  slot_start: string;
  soc_mwh: number | null;
  action_mw: number | null;
  expected_pnl_jpy: number | null;
};

type RegimeRow = {
  slot_start: string;
  p_base: number;
  p_spike: number;
  p_drop: number;
  most_likely_regime: "base" | "spike" | "drop";
};

export async function GET(request: Request) {
  const session = createSessionClient();
  const { data: userData } = await session.auth.getUser();
  const userId = userData.user?.id;
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const url = new URL(request.url);
  const valuationId = url.searchParams.get("valuation_id");
  if (!valuationId) {
    return NextResponse.json({ error: "missing valuation_id" }, { status: 400 });
  }

  const supabase = createServerClient();

  // Ownership check + resolve area_id.
  const { data: vrow, error: ve } = await supabase
    .from("valuations")
    .select("id, user_id, asset_id, horizon_start, horizon_end, assets!inner(area_id)")
    .eq("id", valuationId)
    .maybeSingle();
  if (ve || !vrow) {
    return NextResponse.json({ error: "valuation not found" }, { status: 404 });
  }
  if (vrow.user_id !== userId) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }
  const assetsField = (vrow as { assets: { area_id: string }[] | { area_id: string } | null }).assets;
  const area_id = Array.isArray(assetsField) ? assetsField[0]?.area_id : assetsField?.area_id;
  if (!area_id) {
    return NextResponse.json({ error: "asset has no area_id" }, { status: 500 });
  }

  // Decisions for this valuation.
  const { data: decisions, error: de } = await supabase
    .from("valuation_decisions")
    .select("slot_start, soc_mwh, action_mw, expected_pnl_jpy")
    .eq("valuation_id", valuationId)
    .order("slot_start", { ascending: true });
  if (de) {
    return NextResponse.json({ error: de.message }, { status: 500 });
  }

  // Regime states for the asset's area over the horizon. We pull all model_versions
  // and dedupe per slot_start to the latest.
  const decisionRows = (decisions ?? []) as DecisionRow[];
  const slotStarts = decisionRows.map((d) => d.slot_start);
  let regimes: RegimeRow[] = [];
  if (slotStarts.length > 0) {
    const { data: rs } = await supabase
      .from("regime_states")
      .select("slot_start, p_base, p_spike, p_drop, most_likely_regime, model_version")
      .eq("area_id", area_id)
      .in("slot_start", slotStarts);
    const bySlot = new Map<string, RegimeRow>();
    for (const r of (rs ?? []) as (RegimeRow & { model_version: string })[]) {
      // First entry per slot (server-side ordering not guaranteed but
      // operator should typically have one active version).
      if (!bySlot.has(r.slot_start)) {
        bySlot.set(r.slot_start, {
          slot_start: r.slot_start,
          p_base: Number(r.p_base),
          p_spike: Number(r.p_spike),
          p_drop: Number(r.p_drop),
          most_likely_regime: r.most_likely_regime,
        });
      }
    }
    regimes = Array.from(bySlot.values());
  }

  return NextResponse.json({
    decisions: decisionRows,
    regimes,
  });
}
