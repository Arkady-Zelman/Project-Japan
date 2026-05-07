import { NextResponse } from "next/server";
import { z } from "zod";

import { createServerClient } from "@/lib/supabase/server";

// Section C of /dashboard fetches one (area, slot) curve at a time.
// Return shape mirrors what StackInspector.tsx consumes.

const querySchema = z.object({
  area: z.string().regex(/^[A-Z]{2,3}$/),
  slot: z
    .string()
    .refine((s) => !Number.isNaN(Date.parse(s)), "must be ISO 8601"),
});

export async function GET(request: Request) {
  const url = new URL(request.url);
  const parsed = querySchema.safeParse({
    area: url.searchParams.get("area") ?? "",
    slot: url.searchParams.get("slot") ?? "",
  });
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  const { area, slot } = parsed.data;
  const slotIso = new Date(slot).toISOString();

  const supabase = createServerClient();
  const { data: areaRow, error: areaErr } = await supabase
    .from("areas")
    .select("id, code, name_en")
    .eq("code", area)
    .maybeSingle();
  if (areaErr || !areaRow) {
    return NextResponse.json({ error: `unknown area ${area}` }, { status: 404 });
  }

  const { data: curveRow, error: curveErr } = await supabase
    .from("stack_curves")
    .select("id, curve_jsonb, inputs_hash, created_at")
    .eq("area_id", areaRow.id)
    .eq("slot_start", slotIso)
    .maybeSingle();
  if (curveErr) {
    return NextResponse.json({ error: curveErr.message }, { status: 500 });
  }

  const { data: clearingRow } = await supabase
    .from("stack_clearing_prices")
    .select("modelled_price_jpy_mwh, modelled_demand_mw, marginal_unit_id")
    .eq("area_id", areaRow.id)
    .eq("slot_start", slotIso)
    .maybeSingle();

  const { data: realisedRow } = await supabase
    .from("jepx_spot_prices")
    .select("price_jpy_kwh")
    .eq("area_id", areaRow.id)
    .eq("slot_start", slotIso)
    .eq("auction_type", "day_ahead")
    .maybeSingle();

  let marginalUnitName: string | null = null;
  if (clearingRow?.marginal_unit_id) {
    const { data: gen } = await supabase
      .from("generators")
      .select("name")
      .eq("id", clearingRow.marginal_unit_id)
      .maybeSingle();
    marginalUnitName = gen?.name ?? null;
  }

  return NextResponse.json({
    area: areaRow,
    slot: slotIso,
    curve: curveRow?.curve_jsonb ?? null,
    inputs_hash: curveRow?.inputs_hash ?? null,
    clearing: clearingRow ?? null,
    marginal_unit_name: marginalUnitName,
    realised_jpy_kwh: realisedRow?.price_jpy_kwh ?? null,
  });
}
