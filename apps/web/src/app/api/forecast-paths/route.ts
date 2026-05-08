import { NextResponse } from "next/server";
import { z } from "zod";

import { createServerClient } from "@/lib/supabase/server";

// Section B (forecast fan chart): aggregates the 1000 paths × 48 slots from
// `forecast_paths` into per-slot summary stats so the client can render a
// fan chart without shipping 48k rows over the wire. Optional toggles
// fetch slot-aligned stack model output and most-likely regime label.

const querySchema = z.object({
  area: z.string().regex(/^[A-Z]{2,3}$/),
  origin: z.string().datetime().optional(),    // ISO 8601; defaults to latest run.
  withStack: z.coerce.boolean().default(false),
  withRegime: z.coerce.boolean().default(false),
});

type Slot = {
  slot_start: string;
  mean: number;
  p05: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
  stack: number | null;
  regime: "base" | "spike" | "drop" | null;
};

function quantile(sorted: number[], q: number): number {
  // sorted is ascending; q in [0, 1].
  if (sorted.length === 0) return 0;
  const idx = (sorted.length - 1) * q;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo]!;
  return sorted[lo]! + (sorted[hi]! - sorted[lo]!) * (idx - lo);
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const parsed = querySchema.safeParse({
    area: url.searchParams.get("area") ?? "",
    origin: url.searchParams.get("origin") ?? undefined,
    withStack: url.searchParams.get("withStack") ?? "false",
    withRegime: url.searchParams.get("withRegime") ?? "false",
  });
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  const { area, origin, withStack, withRegime } = parsed.data;

  const supabase = createServerClient();
  const { data: areaRow } = await supabase
    .from("areas")
    .select("id, code, name_en")
    .eq("code", area)
    .maybeSingle();
  if (!areaRow) {
    return NextResponse.json({ error: `unknown area ${area}` }, { status: 404 });
  }

  // Latest forecast_runs row for this area.
  let runQuery = supabase
    .from("forecast_runs")
    .select("id, model_id, forecast_origin, horizon_slots, n_paths, created_at")
    .eq("area_id", areaRow.id)
    .order("forecast_origin", { ascending: false })
    .limit(1);
  if (origin) {
    runQuery = supabase
      .from("forecast_runs")
      .select("id, model_id, forecast_origin, horizon_slots, n_paths, created_at")
      .eq("area_id", areaRow.id)
      .eq("forecast_origin", origin)
      .limit(1);
  }
  const { data: runRow } = await runQuery.maybeSingle();
  if (!runRow) {
    return NextResponse.json({
      area: areaRow, run: null, slots: [],
      note: "No forecast yet for this area. Run vlstm.forecast or wait for the cron.",
    });
  }

  // Fetch all paths for this run. 1000 × 48 = 48k rows; well under
  // Supabase's 1000-row default cap, so we paginate explicitly.
  const PAGE = 1000;
  const totalRows = runRow.n_paths * runRow.horizon_slots;
  const allPaths: { slot_start: string; price_jpy_kwh: number }[] = [];
  for (let from = 0; from < totalRows; from += PAGE) {
    const { data: pageRows, error } = await supabase
      .from("forecast_paths")
      .select("slot_start, price_jpy_kwh")
      .eq("forecast_run_id", runRow.id)
      .order("slot_start", { ascending: true })
      .range(from, Math.min(from + PAGE - 1, totalRows - 1));
    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }
    allPaths.push(...((pageRows ?? []) as { slot_start: string; price_jpy_kwh: number }[]));
  }

  // Group by slot_start, compute stats per slot.
  const bySlot = new Map<string, number[]>();
  for (const r of allPaths) {
    const arr = bySlot.get(r.slot_start) ?? [];
    arr.push(Number(r.price_jpy_kwh));
    bySlot.set(r.slot_start, arr);
  }
  const slotStarts = Array.from(bySlot.keys()).sort();

  // Optional joins.
  let stackBySlot = new Map<string, number>();
  if (withStack && slotStarts.length > 0) {
    const { data: stackRows } = await supabase
      .from("stack_clearing_prices")
      .select("slot_start, modelled_price_jpy_mwh")
      .eq("area_id", areaRow.id)
      .in("slot_start", slotStarts);
    for (const r of stackRows ?? []) {
      stackBySlot.set(
        r.slot_start as string,
        Number(r.modelled_price_jpy_mwh) / 1000,
      );
    }
  }
  let regimeBySlot = new Map<string, "base" | "spike" | "drop">();
  if (withRegime && slotStarts.length > 0) {
    const { data: modelRow } = await supabase
      .from("models")
      .select("version")
      .eq("type", "mrs")
      .eq("name", `mrs_${area}`)
      .eq("status", "ready")
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle();
    if (modelRow) {
      const { data: regimeRows } = await supabase
        .from("regime_states")
        .select("slot_start, most_likely_regime")
        .eq("area_id", areaRow.id)
        .eq("model_version", modelRow.version)
        .in("slot_start", slotStarts);
      for (const r of regimeRows ?? []) {
        regimeBySlot.set(
          r.slot_start as string,
          r.most_likely_regime as "base" | "spike" | "drop",
        );
      }
    }
  }

  const slots: Slot[] = slotStarts.map((s) => {
    const vs = (bySlot.get(s) ?? []).slice().sort((a, b) => a - b);
    const mean = vs.reduce((acc, v) => acc + v, 0) / Math.max(vs.length, 1);
    return {
      slot_start: s,
      mean,
      p05: quantile(vs, 0.05),
      p25: quantile(vs, 0.25),
      p50: quantile(vs, 0.5),
      p75: quantile(vs, 0.75),
      p95: quantile(vs, 0.95),
      stack: stackBySlot.get(s) ?? null,
      regime: regimeBySlot.get(s) ?? null,
    };
  });

  return NextResponse.json({
    area: areaRow,
    run: runRow,
    slots,
  });
}
