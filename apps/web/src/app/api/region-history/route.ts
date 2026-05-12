/**
 * /api/region-history?areas=TK,HK,KS&metric=vre_share&days=30
 *
 * Daily-aggregated historical series per area for the dashboard map's
 * expanded-region chart. Anonymous-readable.
 *
 * Returns rows in wide format (one row per day, one column per area) so
 * Recharts can render multiple Line series directly.
 */

import { NextResponse } from "next/server";

import { createServerClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

const ALLOWED_METRICS = new Set(["vre_share", "balance_pct", "price"]);
const ALLOWED_DAYS = new Set([7, 30, 90]);
const VALID_AREA_CODES = new Set([
  "TK", "HK", "TH", "CB", "HR", "KS", "CG", "SK", "KY",
]);

export async function GET(request: Request) {
  const url = new URL(request.url);
  const metric = url.searchParams.get("metric") ?? "vre_share";
  const daysRaw = Number(url.searchParams.get("days") ?? 30);
  const areasParam = url.searchParams.get("areas") ?? "";
  const areaCodes = areasParam
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter((c) => VALID_AREA_CODES.has(c));

  if (!ALLOWED_METRICS.has(metric)) {
    return NextResponse.json({ error: `invalid metric: ${metric}` }, { status: 400 });
  }
  const days = ALLOWED_DAYS.has(daysRaw) ? daysRaw : 30;
  if (areaCodes.length === 0) {
    return NextResponse.json({ error: "areas query param required" }, { status: 400 });
  }

  const supabase = createServerClient();

  // SQL function returns rows with (day, area_code, value).
  const { data, error } = await (
    supabase.rpc as unknown as (
      fn: string,
      args: { p_area_codes: string[]; p_metric: string; p_days: number },
    ) => Promise<{ data: { day: string; area_code: string; value: number | null }[] | null; error: { message: string } | null }>
  )("region_history", {
    p_area_codes: areaCodes,
    p_metric: metric,
    p_days: days,
  });
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const rows = data ?? [];
  // Pivot into wide format: one row per day, one column per area code.
  const byDay = new Map<string, Record<string, number | null>>();
  for (const r of rows) {
    const dayKey = r.day;
    let day = byDay.get(dayKey);
    if (!day) {
      day = {};
      byDay.set(dayKey, day);
    }
    day[r.area_code] = r.value;
  }
  const points = Array.from(byDay.entries())
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([day, vals]) => ({ day, ...vals }));

  return NextResponse.json({
    metric,
    days,
    areas: areaCodes,
    points,
  });
}
