/**
 * /lab — M8 strategy backtest comparison.
 *
 * Server Component shell: fetches the dev user's assets via server
 * Supabase client, then hands them to the LabClient component which
 * manages the form + Realtime-driven results panel.
 */

import { redirect } from "next/navigation";

import { createServerClient, createSessionClient } from "@/lib/supabase/server";
import { PageHeader } from "@/components/ui/page-header";
import { LabClient } from "@/components/lab/LabClient";

export const dynamic = "force-dynamic";

type RawAssetRow = {
  id: string;
  name: string;
  power_mw: number;
  energy_mwh: number;
  created_at: string;
  area: { code: string }[] | { code: string } | null;
};

async function fetchAssets(userId: string) {
  const supabase = createServerClient();
  const { data } = await supabase
    .from("assets")
    .select("id, name, power_mw, energy_mwh, created_at, area:areas(code)")
    .eq("user_id", userId)
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
  const session = createSessionClient();
  const { data: userData } = await session.auth.getUser();
  if (!userData.user) redirect("/login?next=/lab");
  const assets = await fetchAssets(userData.user.id);

  return (
    <main className="mx-auto max-w-7xl px-6 py-12">
      <PageHeader
        title="Strategy lab"
        description={
          <>
            Backtest one or more dispatch strategies on realised JEPX history.
            Compare cumulative P&amp;L curves, Sharpe, and max drawdown after slippage.
          </>
        }
      />
      <LabClient assets={assets} />
    </main>
  );
}
