/**
 * /api/run-backtest — queue one or more backtest rows, kick the Modal endpoint.
 *
 * Per BUILD_SPEC §6.5: this is the lab's "Run backtest" button target.
 *
 * Flow:
 *   1. zod-validate body.
 *   2. Verify the asset exists and belongs to the dev user.
 *   3. Verify the window has data (>= 48 half-hour slots in jepx_spot_prices).
 *   4. INSERT one `backtests` row per requested strategy with status='queued'.
 *   5. Fire-and-forget POST to MODAL_BACKTEST_ENDPOINT for each backtest_id.
 *   6. Return 202 with `{ backtest_ids }`.
 *
 * Auth: hardcoded dev user (JEPX_DEV_USER_ID env).
 */

import { NextResponse } from "next/server";
import { z } from "zod";

import { createServerClient } from "@/lib/supabase/server";

const MODAL_BACKTEST_ENDPOINT = process.env.MODAL_BACKTEST_ENDPOINT;
const DEV_USER_ID = process.env.JEPX_DEV_USER_ID;

const requestSchema = z.object({
  asset_id: z.string().uuid(),
  window_start: z.string().date(),
  window_end: z.string().date(),
  strategies: z
    .array(z.enum(["lsm", "intrinsic", "rolling_intrinsic", "naive_spread"]))
    .min(1)
    .max(4),
  spread_jpy_kwh: z.number().nonnegative().default(2.0),
  naive_buy_threshold_jpy_kwh: z.number().nonnegative().optional(),
  naive_sell_threshold_jpy_kwh: z.number().nonnegative().optional(),
});

export async function POST(request: Request) {
  if (!DEV_USER_ID) {
    return NextResponse.json(
      { error: "JEPX_DEV_USER_ID env var not set." },
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
  const {
    asset_id, window_start, window_end, strategies,
    spread_jpy_kwh,
    naive_buy_threshold_jpy_kwh,
    naive_sell_threshold_jpy_kwh,
  } = parsed.data;

  if (window_start >= window_end) {
    return NextResponse.json(
      { error: "window_start must be before window_end" },
      { status: 400 },
    );
  }

  const supabase = createServerClient();

  const { data: asset } = await supabase
    .from("assets")
    .select("id, user_id, area_id, name")
    .eq("id", asset_id)
    .maybeSingle();
  if (!asset) {
    return NextResponse.json({ error: `asset ${asset_id} not found` }, { status: 404 });
  }
  if (asset.user_id !== DEV_USER_ID) {
    return NextResponse.json({ error: "asset belongs to another user" }, { status: 403 });
  }

  // Sanity-check that we have at least 48 slots of jepx data in the window.
  const { count: slotCount } = await supabase
    .from("jepx_spot_prices")
    .select("slot_start", { count: "exact", head: true })
    .eq("area_id", asset.area_id)
    .eq("auction_type", "day_ahead")
    .gte("slot_start", `${window_start}T00:00:00Z`)
    .lt("slot_start", `${window_end}T00:00:00Z`);
  if ((slotCount ?? 0) < 48) {
    return NextResponse.json(
      { error: `window has only ${slotCount ?? 0} slots of realised data; need ≥ 48` },
      { status: 409 },
    );
  }

  // Insert one backtests row per strategy.
  const rows = strategies.map((s) => ({
    asset_id,
    user_id: DEV_USER_ID,
    strategy: s,
    window_start,
    window_end,
    status: "queued" as const,
  }));
  const { data: inserted, error: ie } = await supabase
    .from("backtests")
    .insert(rows)
    .select("id, strategy");
  if (ie || !inserted) {
    return NextResponse.json(
      { error: `failed to insert backtests: ${ie?.message ?? "unknown"}` },
      { status: 500 },
    );
  }

  // Fire-and-forget POST per backtest_id to Modal.
  if (MODAL_BACKTEST_ENDPOINT) {
    for (const row of inserted) {
      fetch(MODAL_BACKTEST_ENDPOINT, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          backtest_id: row.id,
          spread_jpy_kwh,
          naive_buy_threshold_jpy_kwh,
          naive_sell_threshold_jpy_kwh,
        }),
      }).catch((e) => console.error("modal run-backtest failed:", row.id, e));
    }
  } else {
    console.warn("MODAL_BACKTEST_ENDPOINT not set; backtests queued but not kicked");
  }

  return NextResponse.json(
    { backtest_ids: inserted.map((r) => ({ id: r.id, strategy: r.strategy })) },
    { status: 202 },
  );
}
