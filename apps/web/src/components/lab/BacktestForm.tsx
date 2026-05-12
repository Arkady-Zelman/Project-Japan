"use client";

import { useMemo, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { captureEvent } from "@/lib/posthog";

const STRATEGIES = [
  { id: "naive_spread", label: "Naive spread" },
  { id: "intrinsic", label: "Intrinsic (perfect foresight)" },
  { id: "rolling_intrinsic", label: "Rolling intrinsic (24h lookahead)" },
  { id: "lsm", label: "LSM (M4 stack-driven)" },
  { id: "lsm_vlstm", label: "LSM (VLSTM-driven)" },
] as const;
type StrategyId = (typeof STRATEGIES)[number]["id"];

const SELECT_CLS =
  "w-full appearance-none rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const INPUT_CLS = SELECT_CLS;

type AssetOption = {
  id: string;
  name: string;
  area_code: string;
  power_mw: number;
  energy_mwh: number;
  created_at: string;
};

type Props = {
  assets: AssetOption[];
  onBacktestsQueued: (ids: string[]) => void;
};

export function BacktestForm({ assets, onBacktestsQueued }: Props) {
  const [assetId, setAssetId] = useState<string>(assets[0]?.id ?? "");
  const [windowStart, setWindowStart] = useState<string>("2026-04-01");
  const [windowEnd, setWindowEnd] = useState<string>("2026-05-01");
  const [strategies, setStrategies] = useState<Set<StrategyId>>(
    new Set<StrategyId>(["naive_spread", "intrinsic", "rolling_intrinsic", "lsm"]),
  );
  const [spreadKwh, setSpreadKwh] = useState<number>(2.0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleStrategy = (id: StrategyId) => {
    setStrategies((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectedAsset = useMemo(
    () => assets.find((a) => a.id === assetId) ?? null,
    [assets, assetId],
  );

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const r = await fetch("/api/run-backtest", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          asset_id: assetId,
          window_start: windowStart,
          window_end: windowEnd,
          strategies: Array.from(strategies),
          spread_jpy_kwh: spreadKwh,
        }),
      });
      const j = await r.json();
      if (!r.ok) {
        throw new Error(j?.error ? JSON.stringify(j.error) : r.statusText);
      }
      const ids = (j.backtest_ids as { id: string; strategy: string }[]).map((row) => row.id);
      captureEvent("backtest_queued", {
        asset_id: assetId,
        strategies: Array.from(strategies),
        window_start: windowStart,
        window_end: windowEnd,
      });
      onBacktestsQueued(ids);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Backtest configuration</CardTitle>
        <CardDescription>
          Pick an asset, a 12-month-or-less window, and one or more strategies
          to compare. Realised JEPX prices drive the simulation; slippage
          model is linear bid-ask half-spread (default ¥2/kWh round-trip).
        </CardDescription>
      </CardHeader>
      <CardContent>
        {assets.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No assets yet. Run a valuation in <a href="/workbench" className="underline">/workbench</a> first.
          </p>
        ) : (
          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="md:col-span-2">
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Asset</label>
                <select
                  className={SELECT_CLS}
                  value={assetId}
                  onChange={(e) => setAssetId(e.target.value)}
                >
                  {assets.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} — {a.area_code} {a.power_mw}MW/{a.energy_mwh}MWh
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Window start</label>
                <input
                  type="date"
                  className={INPUT_CLS}
                  value={windowStart}
                  onChange={(e) => setWindowStart(e.target.value)}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Window end</label>
                <input
                  type="date"
                  className={INPUT_CLS}
                  value={windowEnd}
                  onChange={(e) => setWindowEnd(e.target.value)}
                />
              </div>
              <div className="md:col-span-2">
                <label className="mb-1 block text-xs font-medium text-muted-foreground">Strategies</label>
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  {STRATEGIES.map((s) => (
                    <label
                      key={s.id}
                      className="flex items-center gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={strategies.has(s.id)}
                        onChange={() => toggleStrategy(s.id)}
                      />
                      <span>{s.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>

            <details className="rounded-md border border-foreground/10 px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                Advanced
              </summary>
              <div className="mt-3">
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  Slippage spread (¥/kWh, round-trip)
                </label>
                <input
                  type="number" min={0} step={0.1}
                  className={INPUT_CLS}
                  value={spreadKwh}
                  onChange={(e) => setSpreadKwh(Number(e.target.value))}
                />
              </div>
            </details>

            <div className="rounded-md border border-dashed border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 md:hidden dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
              Read-only on mobile. Switch to desktop to run a backtest.
            </div>
            <div className="hidden items-center gap-3 md:flex">
              <button
                type="submit"
                disabled={submitting || strategies.size === 0}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {submitting ? "Queueing…" : `Run ${strategies.size} backtest${strategies.size === 1 ? "" : "s"}`}
              </button>
              {error && <span className="text-sm text-red-600">Error: {error}</span>}
              {selectedAsset && (
                <span className="text-xs text-muted-foreground">
                  asset id <span className="font-mono">{selectedAsset.id.slice(0, 8)}</span>
                </span>
              )}
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
