import { NextResponse } from "next/server";
import { z } from "zod";

import { createServerClient } from "@/lib/supabase/server";

// Section between Stack inspector and (future) forecast fan: stacked-area
// strip of P(base/spike/drop) over the last N days for the selected area.

const querySchema = z.object({
  area: z.string().regex(/^[A-Z]{2,3}$/),
  days: z.coerce.number().min(1).max(30).default(7),
});

export async function GET(request: Request) {
  const url = new URL(request.url);
  const parsed = querySchema.safeParse({
    area: url.searchParams.get("area") ?? "",
    days: url.searchParams.get("days") ?? "7",
  });
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  const { area, days } = parsed.data;

  const supabase = createServerClient();
  const { data: areaRow } = await supabase
    .from("areas")
    .select("id, code, name_en")
    .eq("code", area)
    .maybeSingle();
  if (!areaRow) {
    return NextResponse.json({ error: `unknown area ${area}` }, { status: 404 });
  }

  // Latest 'ready' MRS model for this area gives us the model_version we
  // want to filter regime_states on (model_versions can coexist).
  const { data: modelRow } = await supabase
    .from("models")
    .select("version, created_at")
    .eq("type", "mrs")
    .eq("name", `mrs_${area}`)
    .eq("status", "ready")
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (!modelRow) {
    return NextResponse.json({
      area: areaRow,
      model_version: null,
      points: [],
      note: "No calibrated MRS model yet for this area.",
    });
  }

  const sinceIso = new Date(Date.now() - days * 86400_000).toISOString();
  const { data: points, error } = await supabase
    .from("regime_states")
    .select("slot_start, p_base, p_spike, p_drop, most_likely_regime")
    .eq("area_id", areaRow.id)
    .eq("model_version", modelRow.version)
    .gte("slot_start", sinceIso)
    .order("slot_start", { ascending: true });
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    area: areaRow,
    model_version: modelRow.version,
    points: points ?? [],
  });
}
