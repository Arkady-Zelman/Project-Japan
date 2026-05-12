/**
 * /api/assets — GET (list current user's assets) + DELETE (?id=...).
 * Auth: Supabase session. 401 if anonymous (middleware also blocks).
 */

import { NextResponse } from "next/server";

import { createServerClient, createSessionClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const session = createSessionClient();
  const { data: userData } = await session.auth.getUser();
  const userId = userData.user?.id;
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const supabase = createServerClient();
  const { data, error } = await supabase
    .from("assets")
    .select(
      "id, name, asset_type, power_mw, energy_mwh, round_trip_eff, soc_min_pct, soc_max_pct, max_cycles_per_year, degradation_jpy_mwh, created_at, area:areas(code)"
    )
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const rows = (data ?? []).map((a) => {
    const areaField = (a as { area: { code: string }[] | { code: string } | null }).area;
    const code = Array.isArray(areaField) ? areaField[0]?.code ?? "??" : areaField?.code ?? "??";
    return {
      id: a.id,
      name: a.name,
      asset_type: a.asset_type,
      area: code,
      power_mw: Number(a.power_mw),
      energy_mwh: Number(a.energy_mwh),
      round_trip_eff: Number(a.round_trip_eff),
      soc_min_pct: Number(a.soc_min_pct),
      soc_max_pct: Number(a.soc_max_pct),
      max_cycles_per_year: Number(a.max_cycles_per_year),
      degradation_jpy_mwh: Number(a.degradation_jpy_mwh),
      created_at: a.created_at,
    };
  });
  return NextResponse.json({ assets: rows });
}

export async function DELETE(request: Request) {
  const session = createSessionClient();
  const { data: userData } = await session.auth.getUser();
  const userId = userData.user?.id;
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const url = new URL(request.url);
  const id = url.searchParams.get("id");
  if (!id) {
    return NextResponse.json({ error: "missing id" }, { status: 400 });
  }

  const supabase = createServerClient();
  const { error } = await supabase
    .from("assets")
    .delete()
    .eq("id", id)
    .eq("user_id", userId);
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
