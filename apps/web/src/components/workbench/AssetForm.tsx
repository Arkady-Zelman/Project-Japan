"use client";

import { useEffect, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { captureEvent } from "@/lib/posthog";

const AREAS = [
  { code: "TK", name: "Tokyo" },
  { code: "HK", name: "Hokkaido" },
  { code: "TH", name: "Tohoku" },
  { code: "CB", name: "Chubu" },
  { code: "HR", name: "Hokuriku" },
  { code: "KS", name: "Kansai" },
  { code: "CG", name: "Chugoku" },
  { code: "SK", name: "Shikoku" },
  { code: "KY", name: "Kyushu" },
] as const;

const ASSET_TYPES = [
  { value: "bess_li_ion", label: "Lithium-ion BESS" },
  { value: "pumped_hydro", label: "Pumped hydro" },
  { value: "compressed_air", label: "Compressed air" },
] as const;

const SELECT_CLS =
  "w-full appearance-none rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const INPUT_CLS = SELECT_CLS;

type AssetFormState = {
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
};

const DEFAULTS: AssetFormState = {
  name: "TK 100MW BESS",
  asset_type: "bess_li_ion",
  area: "TK",
  power_mw: 100,
  energy_mwh: 400,
  round_trip_eff: 0.92,
  soc_min_pct: 0.10,
  soc_max_pct: 0.95,
  max_cycles_per_year: 365,
  degradation_jpy_mwh: 0,
};

type Props = {
  onValuationQueued: (valuation_id: string) => void;
  existingAsset?: (AssetFormState & { id: string }) | null;
  onClearExisting?: () => void;
};

export function AssetForm({ onValuationQueued, existingAsset, onClearExisting }: Props) {
  const [state, setState] = useState<AssetFormState>(existingAsset ?? DEFAULTS);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Hydrate form state when the parent selects an existing asset.
  useEffect(() => {
    if (existingAsset) {
      const { id: _id, ...rest } = existingAsset;
      void _id;
      setState(rest);
    }
  }, [existingAsset]);

  const update = <K extends keyof AssetFormState>(k: K, v: AssetFormState[K]) =>
    setState((s) => ({ ...s, [k]: v }));

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const r = await fetch("/api/value-asset", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(
          existingAsset
            ? { existing_asset_id: existingAsset.id }
            : { asset: state },
        ),
      });
      const j = await r.json();
      if (!r.ok) {
        throw new Error(j?.error ? JSON.stringify(j.error) : r.statusText);
      }
      captureEvent("valuation_queued", {
        area: state.area,
        asset_type: state.asset_type,
        power_mw: state.power_mw,
        energy_mwh: state.energy_mwh,
      });
      onValuationQueued(j.valuation_id);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{existingAsset ? "Run valuation on existing asset" : "Asset configuration"}</CardTitle>
        <CardDescription>
          {existingAsset ? (
            <>
              Re-running an existing asset (<span className="font-mono">{existingAsset.id.slice(0, 8)}</span>) against the latest
              forecast paths. <button type="button" onClick={onClearExisting} className="underline">Clear selection</button> to create a new one.
            </>
          ) : (
            <>
              Configure a storage asset and run an LSM valuation against the latest
              forecast paths for its area. Default is a 100 MW / 400 MWh lithium-ion
              BESS in Tokyo per BUILD_SPEC §12 M7 operator demo.
            </>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={onSubmit}>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Name</label>
              <input
                className={INPUT_CLS}
                value={state.name}
                onChange={(e) => update("name", e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Asset type</label>
              <select
                className={SELECT_CLS}
                value={state.asset_type}
                onChange={(e) =>
                  update("asset_type", e.target.value as AssetFormState["asset_type"])
                }
              >
                {ASSET_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Area</label>
              <select
                className={SELECT_CLS}
                value={state.area}
                onChange={(e) => update("area", e.target.value)}
              >
                {AREAS.map((a) => (
                  <option key={a.code} value={a.code}>
                    {a.name} ({a.code})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Power (MW)</label>
              <input
                type="number" min={0} step={1}
                className={INPUT_CLS}
                value={state.power_mw}
                onChange={(e) => update("power_mw", Number(e.target.value))}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Energy (MWh)</label>
              <input
                type="number" min={0} step={1}
                className={INPUT_CLS}
                value={state.energy_mwh}
                onChange={(e) => update("energy_mwh", Number(e.target.value))}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Round-trip efficiency</label>
              <input
                type="number" min={0} max={1} step={0.01}
                className={INPUT_CLS}
                value={state.round_trip_eff}
                onChange={(e) => update("round_trip_eff", Number(e.target.value))}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">SoC min (fraction)</label>
              <input
                type="number" min={0} max={1} step={0.01}
                className={INPUT_CLS}
                value={state.soc_min_pct}
                onChange={(e) => update("soc_min_pct", Number(e.target.value))}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">SoC max (fraction)</label>
              <input
                type="number" min={0} max={1} step={0.01}
                className={INPUT_CLS}
                value={state.soc_max_pct}
                onChange={(e) => update("soc_max_pct", Number(e.target.value))}
              />
            </div>
          </div>

          <details className="rounded-md border border-foreground/10 px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
              Advanced
            </summary>
            <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Max cycles/year</label>
                <input
                  type="number" min={0} step={1}
                  className={INPUT_CLS}
                  value={state.max_cycles_per_year}
                  onChange={(e) => update("max_cycles_per_year", Number(e.target.value))}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Degradation (¥/MWh)</label>
                <input
                  type="number" min={0} step={1}
                  className={INPUT_CLS}
                  value={state.degradation_jpy_mwh}
                  onChange={(e) => update("degradation_jpy_mwh", Number(e.target.value))}
                />
              </div>
            </div>
          </details>

          <div className="rounded-md border border-dashed border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 md:hidden dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
            Read-only on mobile. Switch to desktop to run a valuation.
          </div>
          <div className="hidden items-center gap-3 md:flex">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {submitting ? "Queueing…" : existingAsset ? "Re-run valuation" : "Run valuation"}
            </button>
            {error && <span className="text-sm text-red-600">Error: {error}</span>}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
