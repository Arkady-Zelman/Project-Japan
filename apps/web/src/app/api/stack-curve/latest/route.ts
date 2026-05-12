/**
 * /api/stack-curve/latest?area=TK
 *
 * Returns the most-recent slot_start for which a stack curve exists in the
 * given area (or system-wide if no area). Used by the dashboard StackInspector
 * to seed its area/date/slot pickers so the tab always opens to something
 * worth looking at instead of "yesterday at noon JST" which usually has no
 * stack data outside the M4 backfill window.
 */

import { NextResponse } from "next/server";

import { createServerClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const area = url.searchParams.get("area");
  const supabase = createServerClient();

  let area_id: string | null = null;
  if (area) {
    const { data: areaRow } = await supabase
      .from("areas")
      .select("id")
      .eq("code", area)
      .maybeSingle();
    if (!areaRow) {
      return NextResponse.json({ slot: null, area }, { status: 200 });
    }
    area_id = areaRow.id;
  }

  let query = supabase
    .from("stack_curves")
    .select("slot_start, area_id, areas!inner(code)")
    .order("slot_start", { ascending: false })
    .limit(1);
  if (area_id) {
    query = query.eq("area_id", area_id);
  }
  const { data, error } = await query.maybeSingle();
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  if (!data) {
    return NextResponse.json({ slot: null, area });
  }
  const areaField = (data as { areas: { code: string }[] | { code: string } }).areas;
  const code = Array.isArray(areaField) ? areaField[0]?.code : areaField?.code;
  return NextResponse.json({
    slot: data.slot_start as string,
    area: code ?? area ?? null,
  });
}
