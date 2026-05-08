"use client";

import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

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
};

export function AssetForm({ onValuationQueued }: Props) {
  const [state, setState] = useState<AssetFormState>(DEFAULTS);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        body: JSON.stringify({ asset: state }),
      });
      const j = await r.json();
      if (!r.ok) {
        throw new Error(j?.error ? JSON.stringify(j.error) : r.statusText);
      }
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
        <CardTitle>Asset configuration</CardTitle>
        <CardDescription>
          Configure a storage asset and run an LSM valuation against the latest
          forecast paths for its area. Default is a 100 MW / 400 MWh lithium-ion
          BESS in Tokyo per BUILD_SPEC §12 M7 operator demo.
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

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {submitting ? "Queueing…" : "Run valuation"}
            </button>
            {error && <span className="text-sm text-red-600">Error: {error}</span>}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
