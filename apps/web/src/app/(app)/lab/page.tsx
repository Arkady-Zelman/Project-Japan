/**
 * /lab — M8 strategy backtest comparison.
 *
 * Server Component shell: fetches the dev user's assets via server
 * Supabase client, then hands them to the LabClient component which
 * manages the form + Realtime-driven results panel.
 */

import { createServerClient } from "@/lib/supabase/server";
import { LabClient } from "@/components/lab/LabClient";

export const dynamic = "force-dynamic";

const DEV_USER_ID = process.env.JEPX_DEV_USER_ID;

type RawAssetRow = {
  id: string;
  name: string;
  power_mw: number;
  energy_mwh: number;
  created_at: string;
  area: { code: string }[] | { code: string } | null;
};

async function fetchAssets() {
  if (!DEV_USER_ID) return [];
  const supabase = createServerClient();
  const { data } = await supabase
    .from("assets")
    .select("id, name, power_mw, energy_mwh, created_at, area:areas(code)")
    .eq("user_id", DEV_USER_ID)
    .order("created_at", { ascending: false });
  return ((data ?? []) as RawAssetRow[]).map((a) => {
    const code = Array.isArray(a.area) ? a.area[0]?.code ?? "??" : a.area?.code ?? "??";
    return {
      id: a.id,
      name: a.name,
      area_code: code,
      power_mw: Number(a.power_mw),
      energy_mwh: Number(a.energy_mwh),
      created_at: a.created_at,
    };
  });
}

export default async function LabPage() {
  const assets = await fetchAssets();

  return (
    <main className="mx-auto max-w-7xl px-6 py-12">
      <header className="mb-10">
        <h1 className="text-3xl font-semibold tracking-tight">Strategy lab</h1>
        <p className="mt-2 text-sm text-neutral-500">
          Backtest one or more dispatch strategies on realised JEPX history.
          Compare cumulative P&L curves, Sharpe, and max drawdown after slippage.
        </p>
      </header>

      <LabClient assets={assets} />
    </main>
  );
}
