/**
 * /api/value-asset — queue an LSM valuation and kick the Modal endpoint.
 *
 * Per BUILD_SPEC §6.4: this is the workbench's "Run valuation" button target.
 *
 * Flow (single transaction up to step 3, then async fire-and-forget):
 *   1. zod-validate body.
 *   2. Resolve area_id from area code.
 *   3. Resolve forecast_run_id (latest run for that area, if not provided).
 *   4. Find or create a dev portfolio for the configured dev user.
 *   5. INSERT a row in `assets` (one-off — we don't reuse existing rows
 *      since v1 has no asset CRUD).
 *   6. INSERT a `valuations` row with status='queued'.
 *   7. Fire-and-forget POST to MODAL_LSM_ENDPOINT with `{valuation_id}`.
 *      The Modal function transitions the row to running → done; the
 *      browser subscribes via Realtime to see the transition.
 *   8. Return 202 `{valuation_id}`.
 *
 * Auth: hardcoded dev user (JEPX_DEV_USER_ID env). Multi-user via Supabase
 * login is M9 territory.
 */

import { NextResponse } from "next/server";
import { z } from "zod";

import { createServerClient } from "@/lib/supabase/server";

const MODAL_LSM_ENDPOINT = process.env.MODAL_LSM_ENDPOINT;
const DEV_USER_ID = process.env.JEPX_DEV_USER_ID;

const requestSchema = z.object({
  asset: z.object({
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
  }),
  forecast_run_id: z.string().uuid().optional(),
});

export async function POST(request: Request) {
  if (!DEV_USER_ID) {
    return NextResponse.json(
      { error: "JEPX_DEV_USER_ID env var not set; see SESSION_LOG_2026-05-08." },
      { status: 500 },
    );
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
  const { asset, forecast_run_id: requestedRunId } = parsed.data;

  const supabase = createServerClient();

  // 2) area_id.
  const { data: areaRow, error: areaErr } = await supabase
    .from("areas")
    .select("id")
    .eq("code", asset.area)
    .maybeSingle();
  if (areaErr || !areaRow) {
    return NextResponse.json(
      { error: `unknown area ${asset.area}` },
      { status: 404 },
    );
  }
  const area_id = areaRow.id;

  // 3) forecast_run_id.
  let forecast_run_id: string | null = requestedRunId ?? null;
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
        { error: `no forecast_run available for area ${asset.area} — run vlstm.forecast first` },
        { status: 409 },
      );
    }
    forecast_run_id = runRow.id;
  }
  // Pull horizon span from the run.
  const { data: runMeta } = await supabase
    .from("forecast_runs")
    .select("forecast_origin, horizon_slots")
    .eq("id", forecast_run_id!)
    .maybeSingle();
  if (!runMeta) {
    return NextResponse.json({ error: "forecast_run not found" }, { status: 404 });
  }
  const horizon_start = runMeta.forecast_origin;
  const horizonEndDate = new Date(
    new Date(horizon_start).getTime() + runMeta.horizon_slots * 30 * 60_000,
  );
  const horizon_end = horizonEndDate.toISOString();

  // 4) dev portfolio.
  let portfolio_id: string;
  const { data: existing } = await supabase
    .from("portfolios")
    .select("id")
    .eq("user_id", DEV_USER_ID)
    .limit(1)
    .maybeSingle();
  if (existing) {
    portfolio_id = existing.id;
  } else {
    const { data: created, error: pe } = await supabase
      .from("portfolios")
      .insert({ user_id: DEV_USER_ID, name: "dev" })
      .select("id")
      .single();
    if (pe || !created) {
      return NextResponse.json(
        { error: `failed to create dev portfolio: ${pe?.message ?? "unknown"}` },
        { status: 500 },
      );
    }
    portfolio_id = created.id;
  }

  // 5) asset.
  const { data: assetRow, error: ae } = await supabase
    .from("assets")
    .insert({
      portfolio_id,
      user_id: DEV_USER_ID,
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

  // 6) valuations.
  const { data: valuationRow, error: ve } = await supabase
    .from("valuations")
    .insert({
      asset_id: assetRow.id,
      user_id: DEV_USER_ID,
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

  // 7) fire-and-forget Modal call.
  if (MODAL_LSM_ENDPOINT) {
    fetch(MODAL_LSM_ENDPOINT, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ valuation_id }),
      // Don't await — the LSM run takes ~30-60s and we want to return now.
    }).catch((e) => {
      // Logged to the Vercel function console; the Modal endpoint also
      // updates the row to status='failed' with the error text.
      console.error("modal lsm-value POST failed:", e);
    });
  } else {
    // Local dev without Modal deployed: the operator runs the LSM via
    // `python -m lsm.runner <valuation_id>` separately.
    console.warn("MODAL_LSM_ENDPOINT not set; valuation queued but not kicked");
  }

  return NextResponse.json({ valuation_id, asset_id: assetRow.id }, { status: 202 });
}
