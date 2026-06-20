/**
 * /api/value-asset — queue an LSM valuation and kick the Modal endpoint.
 *
 * Per BUILD_SPEC §6.4: this is the workbench's "Run valuation" button target.
 *
 * Body shape:
 *   { asset: {...full spec...}, forecast_run_id?: uuid }
 *   - or -
 *   { existing_asset_id: uuid, forecast_run_id?: uuid }
 *
 * Flow (single transaction up to step 3, then async fire-and-forget):
 *   1. zod-validate body.
 *   2. Resolve asset (create new from spec OR look up existing by id+owner).
 *   3. Resolve forecast_run_id (latest for asset's area if not provided).
 *   4. INSERT a `valuations` row with status='queued'.
 *   5. Fire-and-forget POST to MODAL_LSM_ENDPOINT with `{valuation_id}`.
 *   6. Return 202 `{valuation_id, asset_id}`.
 *
 * Auth: Supabase session via cookie. 401 if anonymous (middleware also blocks).
 */

import { NextResponse } from "next/server";
import { z } from "zod";

import { createServerClient, createSessionClient } from "@/lib/supabase/server";

const MODAL_LSM_ENDPOINT = process.env.MODAL_LSM_ENDPOINT;
const MODAL_API_TOKEN = process.env.MODAL_API_TOKEN;

const assetSchema = z.object({
  name: z.string().min(1).max(120),
  asset_type: z.enum(["bess_li_ion", "pumped_hydro", "compressed_air"]),
  area: z.string().regex(/^[A-Z]{2,3}$/),
  power_mw: z.number().positive(),
  energy_mwh: z.number().positive(),
  round_trip_eff: z.number().min(0).max(1),
  soc_min_pct: z.number().min(0).max(1),
  soc_max_pct: z.number().min(0).max(1),
  max_cycles_per_year: z.number().positive(),
  degradation_jpy_mwh: z.number().nonnegative(),
});

const requestSchema = z.union([
  z.object({
    asset: assetSchema,
    forecast_run_id: z.string().uuid().optional(),
  }),
  z.object({
    existing_asset_id: z.string().uuid(),
    forecast_run_id: z.string().uuid().optional(),
  }),
]);

export async function POST(request: Request) {
  const session = createSessionClient();
  const { data: userData } = await session.auth.getUser();
  const userId = userData.user?.id;
  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }
  const parsed = requestSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  if (MODAL_LSM_ENDPOINT && !MODAL_API_TOKEN) {
    return NextResponse.json(
      { error: "MODAL_API_TOKEN not configured" },
      { status: 500 },
    );
  }

  const supabase = createServerClient();

  let area_id: string;
  let asset_id: string;

  if ("existing_asset_id" in parsed.data) {
    // Look up existing asset; verify ownership.
    const { data: row, error } = await supabase
      .from("assets")
      .select("id, user_id, area_id")
      .eq("id", parsed.data.existing_asset_id)
      .maybeSingle();
    if (error || !row) {
      return NextResponse.json({ error: "asset not found" }, { status: 404 });
    }
    if (row.user_id !== userId) {
      return NextResponse.json({ error: "asset belongs to another user" }, { status: 403 });
    }
    asset_id = row.id;
    area_id = row.area_id;
  } else {
    const { asset } = parsed.data;
    // Resolve area_id from code.
    const { data: areaRow, error: areaErr } = await supabase
      .from("areas")
      .select("id")
      .eq("code", asset.area)
      .maybeSingle();
    if (areaErr || !areaRow) {
      return NextResponse.json({ error: `unknown area ${asset.area}` }, { status: 404 });
    }
    area_id = areaRow.id;

    // Find or create the user's portfolio.
    let portfolio_id: string;
    const { data: existing } = await supabase
      .from("portfolios")
      .select("id")
      .eq("user_id", userId)
      .limit(1)
      .maybeSingle();
    if (existing) {
      portfolio_id = existing.id;
    } else {
      const { data: created, error: pe } = await supabase
        .from("portfolios")
        .insert({ user_id: userId, name: "default" })
        .select("id")
        .single();
      if (pe || !created) {
        return NextResponse.json(
          { error: `failed to create portfolio: ${pe?.message ?? "unknown"}` },
          { status: 500 },
        );
      }
      portfolio_id = created.id;
    }

    // INSERT the asset.
    const { data: assetRow, error: ae } = await supabase
      .from("assets")
      .insert({
        portfolio_id,
        user_id: userId,
        name: asset.name,
        asset_type: asset.asset_type,
        area_id,
        power_mw: asset.power_mw,
        energy_mwh: asset.energy_mwh,
        round_trip_eff: asset.round_trip_eff,
        soc_min_pct: asset.soc_min_pct,
        soc_max_pct: asset.soc_max_pct,
        max_cycles_per_year: asset.max_cycles_per_year,
        degradation_jpy_mwh: asset.degradation_jpy_mwh,
      })
      .select("id")
      .single();
    if (ae || !assetRow) {
      return NextResponse.json(
        { error: `failed to insert asset: ${ae?.message ?? "unknown"}` },
        { status: 500 },
      );
    }
    asset_id = assetRow.id;
  }

  // Resolve forecast_run_id.
  let forecast_run_id: string | null = parsed.data.forecast_run_id ?? null;
  if (!forecast_run_id) {
    const { data: runRow } = await supabase
      .from("forecast_runs")
      .select("id, forecast_origin")
      .eq("area_id", area_id)
      .order("forecast_origin", { ascending: false })
      .limit(1)
      .maybeSingle();
    if (!runRow) {
      return NextResponse.json(
        { error: `no forecast_run available for area ${area_id} — run vlstm.forecast first` },
        { status: 409 },
      );
    }
    forecast_run_id = runRow.id;
  }
  const { data: runMeta } = await supabase
    .from("forecast_runs")
    .select("forecast_origin, horizon_slots")
    .eq("id", forecast_run_id)
    .maybeSingle();
  if (!runMeta) {
    return NextResponse.json({ error: "forecast_run not found" }, { status: 404 });
  }
  const horizon_start = runMeta.forecast_origin;
  const horizonEndDate = new Date(
    new Date(horizon_start).getTime() + runMeta.horizon_slots * 30 * 60_000,
  );
  const horizon_end = horizonEndDate.toISOString();

  // INSERT valuation row.
  const { data: valuationRow, error: ve } = await supabase
    .from("valuations")
    .insert({
      asset_id,
      user_id: userId,
      forecast_run_id,
      method: "lsm",
      status: "queued",
      horizon_start,
      horizon_end,
      basis_functions: { basis: "power" },
      n_paths: 1000,
      n_volume_grid: 101,
    })
    .select("id")
    .single();
  if (ve || !valuationRow) {
    return NextResponse.json(
      { error: `failed to insert valuation: ${ve?.message ?? "unknown"}` },
      { status: 500 },
    );
  }
  const valuation_id = valuationRow.id;

  // Fire-and-forget Modal call.
  if (MODAL_LSM_ENDPOINT) {
    fetch(MODAL_LSM_ENDPOINT, {
      method: "POST",
      headers: {
        "authorization": `Bearer ${MODAL_API_TOKEN}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ valuation_id }),
    }).catch((e) => {
      console.error("modal lsm-value POST failed:", e);
    });
  } else {
    console.warn("MODAL_LSM_ENDPOINT not set; valuation queued but not kicked");
  }

  return NextResponse.json({ valuation_id, asset_id }, { status: 202 });
}
