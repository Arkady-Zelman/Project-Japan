/**
 * /api/bos-strategy?asset_id=…&source=forecast|realised&horizon_slots=48
 *
 * Pulls the requested forward curve, runs the BoS optimisation, returns the
 * basket + value breakdown + per-day physical profile + per-slot tradeable
 * view.
 *
 * Auth: optional. Logged-in users see results for their own asset (first by
 * default, or `?asset_id=…` explicitly — explicit IDs require auth so we
 * don't leak other users' assets). Anonymous viewers get a synthetic demo
 * asset in Tokyo so the public dashboard demonstrates the methodology.
 */

import { NextResponse } from "next/server";

import { createServerClient, createSessionClient } from "@/lib/supabase/server";
import { runBoS, type ForwardPoint } from "@/lib/bos-strategy";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

const DEFAULT_HORIZON_SLOTS = 48;
const REALISED_LOOKBACK_DAYS = 28;

export async function GET(request: Request) {
  const session = createSessionClient();
  const { data: userData } = await session.auth.getUser();
  const userId = userData.user?.id;

  const url = new URL(request.url);
  const sourceParam = url.searchParams.get("source") ?? "forecast";
  const source: "forecast" | "realised" =
    sourceParam === "realised" ? "realised" : "forecast";
  const horizonSlots = Math.min(
    Math.max(Number(url.searchParams.get("horizon_slots") ?? DEFAULT_HORIZON_SLOTS), 8),
    336,
  );
  const explicitAssetId = url.searchParams.get("asset_id");

  // Explicit asset_id implies "show *this* user's asset", so require auth.
  if (explicitAssetId && !userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const supabase = createServerClient();

  // Try to find a real asset for the logged-in user, if any.
  type AssetRow = {
    id: string;
    name: string;
    area_id: string;
    power_mw: number | string;
    energy_mwh: number | string;
    round_trip_eff: number | string;
    soc_min_pct: number | string;
    soc_max_pct: number | string;
    areas: { code: string }[] | { code: string };
  };
  let realAsset: AssetRow | null = null;
  if (userId) {
    const q = supabase
      .from("assets")
      .select(
        "id, name, area_id, power_mw, energy_mwh, round_trip_eff, soc_min_pct, soc_max_pct, areas!inner(code, name_en)",
      )
      .eq("user_id", userId);
    const { data, error } = await (
      explicitAssetId
        ? q.eq("id", explicitAssetId).maybeSingle()
        : q.limit(1).maybeSingle()
    );
    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }
    realAsset = (data as AssetRow | null) ?? null;
  }

  // Resolve area + asset spec. Anonymous viewers (and logged-in users with
  // no assets yet) get a synthetic 100 MWh / 50 MW BESS in Tokyo so the
  // public dashboard always has something to render.
  let area_id: string;
  let areaCode: string | undefined;
  let assetMeta: { id: string; name: string };
  let assetSpec: {
    power_mw: number;
    energy_mwh: number;
    round_trip_eff: number;
    soc_min_pct: number;
    soc_max_pct: number;
  };

  if (realAsset) {
    const areaField = realAsset.areas;
    areaCode = Array.isArray(areaField) ? areaField[0]?.code : areaField?.code;
    area_id = realAsset.area_id;
    assetMeta = { id: realAsset.id, name: realAsset.name };
    assetSpec = {
      power_mw: Number(realAsset.power_mw),
      energy_mwh: Number(realAsset.energy_mwh),
      round_trip_eff: Number(realAsset.round_trip_eff),
      soc_min_pct: Number(realAsset.soc_min_pct),
      soc_max_pct: Number(realAsset.soc_max_pct),
    };
  } else {
    const { data: areaRow } = await supabase
      .from("areas")
      .select("id, code")
      .eq("code", "TK")
      .maybeSingle();
    if (!areaRow) {
      return NextResponse.json(
        { error: "Tokyo area not found in database" },
        { status: 500 },
      );
    }
    area_id = areaRow.id as string;
    areaCode = areaRow.code as string;
    assetMeta = { id: "demo", name: "Demo: 100 MWh / 50 MW BESS (Tokyo)" };
    assetSpec = {
      power_mw: 50,
      energy_mwh: 100,
      round_trip_eff: 0.85,
      soc_min_pct: 10,
      soc_max_pct: 90,
    };
  }

  // Pull the forward curve.
  let forward: ForwardPoint[] = [];
  if (source === "forecast") {
    forward = await buildForecastCurve(supabase, area_id, horizonSlots);
  }
  // Fall back to realised if no forecast available.
  if (forward.length === 0) {
    forward = await buildRealisedCurve(supabase, area_id, horizonSlots);
  }
  if (forward.length === 0) {
    return NextResponse.json(
      { error: "no forward data available for area" },
      { status: 409 },
    );
  }

  const result = runBoS(forward, assetSpec, { dt_hours: 0.5, corr_decay_hours: 24 });

  return NextResponse.json({
    source: forward.length > 0 ? source : "realised",
    asset: {
      id: assetMeta.id,
      name: assetMeta.name,
      area: areaCode,
      power_mw: assetSpec.power_mw,
      energy_mwh: assetSpec.energy_mwh,
      round_trip_eff: assetSpec.round_trip_eff,
    },
    horizon_slots: forward.length,
    dt_hours: 0.5,
    ...result,
  });
}

/**
 * Build a per-slot forward curve from the latest VLSTM forecast_run for the
 * area. Returns mean price + stdev across paths per slot.
 */
async function buildForecastCurve(
  supabase: ReturnType<typeof createServerClient>,
  area_id: string,
  horizon_slots: number,
): Promise<ForwardPoint[]> {
  const { data: run } = await supabase
    .from("forecast_runs")
    .select("id, forecast_origin, horizon_slots")
    .eq("area_id", area_id)
    .order("forecast_origin", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (!run) return [];

  const origin = new Date(run.forecast_origin as string);
  // Slot grid is half-hourly starting at forecast_origin. Cap to whichever
  // is smaller: requested horizon, or the run's actual horizon_slots.
  const usedHorizon = Math.min(horizon_slots, Number(run.horizon_slots) || horizon_slots);
  const horizonEnd = new Date(origin.getTime() + usedHorizon * 30 * 60 * 1000).toISOString();

  // Pull all path × slot rows for that run within the horizon. Supabase
  // server-side caps at ~1000 rows/page, so paginate via .range until done.
  const all: { slot_start: string; price_jpy_kwh: number }[] = [];
  const pageSize = 1000;
  let from = 0;
  // 9 utilities is irrelevant here — we're per-area. Cap pages to a safety
  // limit; 1000 paths × 48 slots = 48k rows / 1000 page = 48 pages.
  for (let page = 0; page < 200; page++) {
    const { data, error } = await supabase
      .from("forecast_paths")
      .select("slot_start, price_jpy_kwh")
      .eq("forecast_run_id", run.id)
      .lt("slot_start", horizonEnd)
      .range(from, from + pageSize - 1);
    if (error || !data || data.length === 0) break;
    for (const r of data as { slot_start: string; price_jpy_kwh: number | string }[]) {
      all.push({ slot_start: r.slot_start, price_jpy_kwh: Number(r.price_jpy_kwh) });
    }
    if (data.length < pageSize) break;
    from += pageSize;
  }
  if (all.length === 0) return [];

  // Aggregate to mean + stdev per slot_start, derive `ix` from time offset.
  const by_slot = new Map<string, number[]>();
  for (const p of all) {
    const arr = by_slot.get(p.slot_start) ?? [];
    arr.push(p.price_jpy_kwh);
    by_slot.set(p.slot_start, arr);
  }
  const out: ForwardPoint[] = [];
  for (const [ts, prices] of Array.from(by_slot.entries()).sort()) {
    if (prices.length === 0) continue;
    let sum = 0;
    for (const v of prices) sum += v;
    const mean = sum / prices.length;
    let var_ = 0;
    for (const v of prices) var_ += (v - mean) * (v - mean);
    const vol = Math.sqrt(var_ / Math.max(prices.length - 1, 1));
    const ix = Math.round((new Date(ts).getTime() - origin.getTime()) / (30 * 60 * 1000));
    out.push({ ix, ts, price: mean, vol });
  }
  return out;
}

/**
 * Build a realised-history forward curve: for each upcoming slot, take the
 * mean + stdev of the same weekday × hour-of-day from the last N days of
 * realised JEPX day-ahead prices.
 */
async function buildRealisedCurve(
  supabase: ReturnType<typeof createServerClient>,
  area_id: string,
  horizon_slots: number,
): Promise<ForwardPoint[]> {
  const now = new Date();
  // Round to the next half-hour boundary.
  now.setUTCSeconds(0, 0);
  now.setUTCMinutes(now.getUTCMinutes() < 30 ? 30 : 0);
  if (now.getUTCMinutes() === 0) {
    now.setUTCHours(now.getUTCHours() + 1);
  }
  const since = new Date(now.getTime() - REALISED_LOOKBACK_DAYS * 24 * 3600 * 1000);

  const { data: rows } = await supabase
    .from("jepx_spot_prices")
    .select("slot_start, price_jpy_kwh")
    .eq("area_id", area_id)
    .eq("auction_type", "day_ahead")
    .gte("slot_start", since.toISOString())
    .order("slot_start", { ascending: true });
  if (!rows || rows.length === 0) return [];

  // Bucket by (weekday, halfhour-of-day).
  const buckets = new Map<string, number[]>();
  for (const r of rows as { slot_start: string; price_jpy_kwh: number | null }[]) {
    if (r.price_jpy_kwh == null) continue;
    const d = new Date(r.slot_start);
    const key = `${d.getUTCDay()}-${d.getUTCHours()}-${d.getUTCMinutes()}`;
    const arr = buckets.get(key) ?? [];
    arr.push(Number(r.price_jpy_kwh));
    buckets.set(key, arr);
  }

  const out: ForwardPoint[] = [];
  for (let ix = 0; ix < horizon_slots; ix++) {
    const ts = new Date(now.getTime() + ix * 30 * 60 * 1000);
    const key = `${ts.getUTCDay()}-${ts.getUTCHours()}-${ts.getUTCMinutes()}`;
    const arr = buckets.get(key) ?? [];
    if (arr.length === 0) continue;
    let sum = 0;
    for (const v of arr) sum += v;
    const mean = sum / arr.length;
    let var_ = 0;
    for (const v of arr) var_ += (v - mean) * (v - mean);
    const vol = Math.sqrt(var_ / Math.max(arr.length - 1, 1));
    out.push({ ix, ts: ts.toISOString(), price: mean, vol });
  }
  return out;
}
