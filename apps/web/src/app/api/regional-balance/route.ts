/**
 * /api/regional-balance — one row per JEPX utility area for the latest
 * half-hourly slot that has demand data. Anonymous-readable.
 *
 * Returns demand, generation mix, balance %, and JEPX day-ahead clearing.
 * Used by the dashboard Japan map + the system-wide hero metric strip.
 */

import { NextResponse } from "next/server";

import { createServerClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

type AreaRow = { id: string; code: string; name_en: string };
type DemandRow = { area_id: string; demand_mw: number | null };
type GenRow = { area_id: string; fuel_type_id: string; output_mw: number | null };
type FuelRow = { id: string; code: string };
type PriceRow = { area_id: string; price_jpy_kwh: number | null };

export type RegionalBalance = {
  code: string;
  name: string;
  slot_start: string;
  demand_mw: number | null;
  generation: { fuel_code: string; output_mw: number }[];
  total_gen_mw: number;
  vre_share: number;
  price_jpy_kwh: number | null;
  balance_pct: number | null;
};

const VRE_FUELS = new Set(["solar", "wind", "hydro", "vre"]);

export async function GET() {
  const supabase = createServerClient();

  // Pick the latest slot where every JEPX utility has non-null demand. That
  // way the dashboard's first paint looks complete instead of mixing live TK
  // data with HK/TH placeholders (those two utilities publish 1-2 days late).
  // Walks back coverage thresholds 9 → 8 → 7 so we always pick the best
  // recent snapshot. RPC defined in supabase/migrations/005_*.sql.
  let slot_start: string | null = null;
  for (const minAreas of [9, 8, 7]) {
    // The generated DB types don't include this newly-added function — cast
    // through `unknown` and call without the typed-args overhead.
    const { data, error } = await (
      supabase.rpc as unknown as (
        fn: string,
        args: Record<string, unknown>,
      ) => Promise<{ data: string | null; error: { message: string } | null }>
    )("latest_full_coverage_slot", {
      lookback_days: 14,
      min_areas: minAreas,
    });
    if (error) {
      console.error("latest_full_coverage_slot rpc failed:", error);
      break;
    }
    if (data) {
      slot_start = data as unknown as string;
      break;
    }
  }
  if (!slot_start) {
    const { data: latestRow } = await supabase
      .from("demand_actuals")
      .select("slot_start")
      .order("slot_start", { ascending: false })
      .limit(1)
      .maybeSingle();
    if (!latestRow) {
      return NextResponse.json({ slot_start: null, rows: [] });
    }
    slot_start = latestRow.slot_start as string;
  }

  const [
    areasRes,
    fuelsRes,
    demandsRes,
    gensRes,
    pricesRes,
  ] = await Promise.all([
    supabase.from("areas").select("id, code, name_en"),
    supabase.from("fuel_types").select("id, code"),
    supabase
      .from("demand_actuals")
      .select("area_id, demand_mw")
      .eq("slot_start", slot_start),
    supabase
      .from("generation_mix_actuals")
      .select("area_id, fuel_type_id, output_mw")
      .eq("slot_start", slot_start),
    supabase
      .from("jepx_spot_prices")
      .select("area_id, price_jpy_kwh")
      .eq("slot_start", slot_start)
      .eq("auction_type", "day_ahead"),
  ]);

  for (const [name, res] of [
    ["areas", areasRes],
    ["fuels", fuelsRes],
    ["demands", demandsRes],
    ["gens", gensRes],
    ["prices", pricesRes],
  ] as const) {
    if (res.error) {
      console.error(`regional-balance: ${name} fetch failed:`, res.error);
      return NextResponse.json(
        { error: `${name} query: ${res.error.message}` },
        { status: 500 },
      );
    }
  }

  const areas = areasRes.data;
  const fuels = fuelsRes.data;
  const demands = demandsRes.data;
  const gens = gensRes.data;
  const prices = pricesRes.data;

  const fuelById = new Map<string, string>(
    ((fuels ?? []) as FuelRow[]).map((f) => [f.id, f.code]),
  );
  const demandByArea = new Map<string, number | null>(
    ((demands ?? []) as DemandRow[]).map((d) => [d.area_id, d.demand_mw]),
  );
  const priceByArea = new Map<string, number | null>(
    ((prices ?? []) as PriceRow[]).map((p) => [p.area_id, p.price_jpy_kwh]),
  );
  const genByArea = new Map<string, { fuel_code: string; output_mw: number }[]>();
  for (const g of (gens ?? []) as GenRow[]) {
    const fuel_code = fuelById.get(g.fuel_type_id);
    if (!fuel_code || g.output_mw == null) continue;
    const list = genByArea.get(g.area_id) ?? [];
    list.push({ fuel_code, output_mw: Number(g.output_mw) });
    genByArea.set(g.area_id, list);
  }

  const rows: RegionalBalance[] = ((areas ?? []) as AreaRow[])
    .filter((a) => a.code !== "SYS")
    .map((a) => {
      const generation = genByArea.get(a.id) ?? [];
      const total_gen_mw = generation.reduce((s, x) => s + x.output_mw, 0);
      const vre_mw = generation
        .filter((g) => VRE_FUELS.has(g.fuel_code))
        .reduce((s, x) => s + x.output_mw, 0);
      const vre_share = total_gen_mw > 0 ? vre_mw / total_gen_mw : 0;
      const demand_mw = demandByArea.get(a.id) ?? null;
      const price_jpy_kwh = priceByArea.get(a.id) ?? null;
      const balance_pct =
        demand_mw != null && demand_mw > 0
          ? (total_gen_mw - demand_mw) / demand_mw
          : null;
      return {
        code: a.code,
        name: a.name_en,
        slot_start,
        demand_mw: demand_mw != null ? Number(demand_mw) : null,
        generation,
        total_gen_mw,
        vre_share,
        price_jpy_kwh: price_jpy_kwh != null ? Number(price_jpy_kwh) : null,
        balance_pct,
      };
    });

  return NextResponse.json({ slot_start, rows });
}
