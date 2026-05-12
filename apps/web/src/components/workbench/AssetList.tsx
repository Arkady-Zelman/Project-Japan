"use client";

/**
 * My assets pane on /workbench.
 *
 *  - Lists the current user's existing assets
 *  - Click a row → calls onSelect to prefill the AssetForm with that asset
 *  - Delete button cascades to valuations via ON DELETE CASCADE
 */

import { useCallback, useEffect, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export type AssetRow = {
  id: string;
  name: string;
  asset_type: "bess_li_ion" | "pumped_hydro" | "compressed_air";
  area: string;
  power_mw: number;
  energy_mwh: number;
  round_trip_eff: number;
  soc_min_pct: number;
  soc_max_pct: number;
  max_cycles_per_year: number;
  degradation_jpy_mwh: number;
  created_at: string;
};

type Props = {
  onSelect: (asset: AssetRow) => void;
  selectedId: string | null;
};

export function AssetList({ onSelect, selectedId }: Props) {
  const [assets, setAssets] = useState<AssetRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const r = await fetch("/api/assets");
      if (!r.ok) {
        if (r.status === 401) {
          setAssets([]);
          return;
        }
        const j = await r.json().catch(() => ({}));
        throw new Error(j?.error ?? r.statusText);
      }
      const j = (await r.json()) as { assets: AssetRow[] };
      setAssets(j.assets);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onDelete = async (id: string) => {
    setPendingDelete(id);
    try {
      const r = await fetch(`/api/assets?id=${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j?.error ?? r.statusText);
      }
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setPendingDelete(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>My assets</CardTitle>
        <CardDescription>Click a row to load it into the form, or delete.</CardDescription>
      </CardHeader>
      <CardContent>
        {assets === null && (
          <div className="space-y-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        )}
        {error && <p className="text-sm text-red-600">Error: {error}</p>}
        {assets && assets.length === 0 && (
          <p className="text-sm text-muted-foreground">No assets yet — create one with the form below.</p>
        )}
        {assets && assets.length > 0 && (
          <ul className="space-y-1">
            {assets.map((a) => {
              const selected = selectedId === a.id;
              return (
                <li key={a.id} className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onSelect(a)}
                    className={`flex-1 rounded-md border-l-2 px-3 py-2 text-left text-sm transition hover:bg-muted ${
                      selected
                        ? "border-l-[#1d4ed8] bg-muted/60"
                        : "border-l-transparent"
                    }`}
                  >
                    <div className="font-medium">{a.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {a.area} · {a.power_mw} MW / {a.energy_mwh} MWh · {a.asset_type}
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(a.id)}
                    disabled={pendingDelete === a.id}
                    className="rounded-md border border-foreground/10 px-2 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
                  >
                    {pendingDelete === a.id ? "…" : "Delete"}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
