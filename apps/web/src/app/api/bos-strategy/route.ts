/**
 * /api/bos-strategy?asset_id=…&source=forecast|realised&horizon_slots=48
 *
 * Pulls the requested forward curve, runs the BoS optimisation, returns the
 * basket + value breakdown + per-day physical profile + per-slot tradeable
 * view. Auth-required since results are user-asset-specific.
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
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const url = new URL(request.url);
  const sourceParam = url.searchParams.get("source") ?? "forecast";
  const source: "forecast" | "realised" =
    sourceParam === "realised" ? "realised" : "forecast";
  const horizonSlots = Math.min(
    Math.max(Number(url.searchParams.get("horizon_slots") ?? DEFAULT_HORIZON_SLOTS), 8),
    336,
  );

  const supabase = createServerClient();

  // Resolve the asset — explicit asset_id wins, otherwise default to user's
  // first asset.
  const assetId = url.searchParams.get("asset_id");
  const assetQuery = supabase
    .from("assets")
    .select(
      "id, name, area_id, power_mw, energy_mwh, round_trip_eff, soc_min_pct, soc_max_pct, areas!inner(code, name_en)",
    )
    .eq("user_id", userId);
  const { data: assetRow, error: assetErr } = await (
    assetId ? assetQuery.eq("id", assetId).maybeSingle() : assetQuery.limit(1).maybeSingle()
  );
  if (assetErr) {
    return NextResponse.json({ error: assetErr.message }, { status: 500 });
  }
  if (!assetRow) {
    return NextResponse.json({ error: "no asset found for user" }, { status: 404 });
  }
  const area_id = assetRow.area_id as string;
  const areaField = (assetRow as { areas: { code: string }[] | { code: string } }).areas;
  const areaCode = Array.isArray(areaField) ? areaField[0]?.code : areaField?.code;

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

  const asset = {
    power_mw: Number(assetRow.power_mw),
    energy_mwh: Number(assetRow.energy_mwh),
    round_trip_eff: Number(assetRow.round_trip_eff),
    soc_min_pct: Number(assetRow.soc_min_pct),
    soc_max_pct: Number(assetRow.soc_max_pct),
  };

  const result = runBoS(forward, asset, { dt_hours: 0.5, corr_decay_hours: 24 });

  return NextResponse.json({
    source: forward.length > 0 ? source : "realised",
    asset: {
      id: assetRow.id,
      name: assetRow.name,
      area: areaCode,
      power_mw: asset.power_mw,
      energy_mwh: asset.energy_mwh,
      round_trip_eff: asset.round_trip_eff,
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
