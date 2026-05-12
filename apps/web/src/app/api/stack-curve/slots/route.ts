/**
 * /api/stack-curve/slots?area=TK&date=2026-05-12
 *
 * Returns the half-hour slot_start timestamps where `stack_curves` actually
 * has data for the given (area, JST-date). StackInspector uses this to
 * populate its slot dropdown so the operator only ever picks something that
 * will render — not the 48 half-hours of which most are empty.
 */

import { NextResponse } from "next/server";

import { createServerClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const area = url.searchParams.get("area");
  const dateStr = url.searchParams.get("date"); // YYYY-MM-DD JST
  if (!area || !dateStr) {
    return NextResponse.json({ error: "area and date required" }, { status: 400 });
  }

  const supabase = createServerClient();
  const { data: areaRow } = await supabase
    .from("areas")
    .select("id")
    .eq("code", area)
    .maybeSingle();
  if (!areaRow) {
    return NextResponse.json({ slots: [] });
  }

  // JST midnight → UTC: subtract 9h. Window is [jstStart, jstStart + 24h).
  const jstStartUtc = new Date(`${dateStr}T00:00:00+09:00`).toISOString();
  const jstEndUtc = new Date(
    new Date(`${dateStr}T00:00:00+09:00`).getTime() + 24 * 3600 * 1000,
  ).toISOString();

  const { data, error } = await supabase
    .from("stack_curves")
    .select("slot_start")
    .eq("area_id", areaRow.id)
    .gte("slot_start", jstStartUtc)
    .lt("slot_start", jstEndUtc)
    .order("slot_start", { ascending: true });
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({
    slots: ((data ?? []) as { slot_start: string }[]).map((r) => r.slot_start),
  });
}
