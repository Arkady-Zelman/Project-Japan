"use client";

/**
 * Decision heatmap — slot × regime grid showing expected P&L weighted by
 * regime probability. Reads /api/valuation-decisions.
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
import { createBrowserClient } from "@/lib/supabase/client";

type DecisionRow = {
  slot_start: string;
  soc_mwh: number | null;
  action_mw: number | null;
  expected_pnl_jpy: number | null;
};

type RegimeRow = {
  slot_start: string;
  p_base: number;
  p_spike: number;
  p_drop: number;
  most_likely_regime: "base" | "spike" | "drop";
};

const REGIMES: ReadonlyArray<"base" | "spike" | "drop"> = ["base", "spike", "drop"];

function colorForValue(v: number, vMax: number): string {
  if (vMax === 0) return "rgb(255,255,255)";
  const t = Math.min(1, Math.abs(v) / vMax);
  if (v >= 0) {
    // green
    const a = Math.round(20 + 200 * t);
    return `rgb(34,${a},94)`;
  }
  // red
  const a = Math.round(20 + 200 * t);
  return `rgb(${a},38,38)`;
}

export function DecisionHeatmap({ valuationId }: { valuationId: string | null }) {
  const [decisions, setDecisions] = useState<DecisionRow[] | null>(null);
  const [regimes, setRegimes] = useState<RegimeRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    if (!valuationId) return;
    try {
      const r = await fetch(
        `/api/valuation-decisions?valuation_id=${encodeURIComponent(valuationId)}`,
      );
      const j = await r.json();
      if (!r.ok) throw new Error(j?.error?.toString() ?? r.statusText);
      const parsed = j as { decisions: DecisionRow[]; regimes: RegimeRow[] };
      setDecisions(parsed.decisions);
      setRegimes(parsed.regimes);
    } catch (e) {
      setError(String(e));
    }
  }, [valuationId]);

  useEffect(() => {
    if (!valuationId) {
      setDecisions(null);
      setRegimes([]);
      return;
    }
    setDecisions(null);
    setError(null);
    void refetch();
  }, [valuationId, refetch]);

  // Realtime: refetch when valuation_decisions rows land for this valuation,
  // OR when the parent valuation transitions queued → running → done.
  useEffect(() => {
    if (!valuationId) return;
    let supa;
    try {
      supa = createBrowserClient();
    } catch {
      return;
    }
    const channel = supa
      .channel(`workbench-heatmap-${valuationId}-${Math.random().toString(36).slice(2)}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "valuation_decisions",
          filter: `valuation_id=eq.${valuationId}`,
        },
        () => void refetch(),
      )
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "valuations",
          filter: `id=eq.${valuationId}`,
        },
        () => void refetch(),
      )
      .subscribe();
    return () => {
      supa.removeChannel(channel);
    };
  }, [valuationId, refetch]);

  if (!valuationId) return null;

  const regimeBySlot = new Map<string, RegimeRow>(regimes.map((r) => [r.slot_start, r]));
  const vMax =
    decisions && decisions.length
      ? Math.max(...decisions.map((d) => Math.abs(d.expected_pnl_jpy ?? 0)), 1)
      : 1;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Decision heatmap</CardTitle>
        <CardDescription>
          Per-slot expected P&amp;L weighted by regime probability. Green = profitable
          under that regime; red = unprofitable. Empty cells mean no regime probability
          available for that slot.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error && <p className="text-sm text-red-600">Error: {error}</p>}
        {decisions === null && !error && (
          <div className="space-y-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-[180px] w-full" />
          </div>
        )}
        {decisions && decisions.length === 0 && (
          <p className="text-sm text-muted-foreground">No decision rows yet.</p>
        )}
        {decisions && decisions.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="px-2 py-1 font-medium">Slot</th>
                  {REGIMES.map((r) => (
                    <th key={r} className="px-2 py-1 font-medium capitalize">
                      {r}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {decisions.map((d) => {
                  const rs = regimeBySlot.get(d.slot_start);
                  const pnl = d.expected_pnl_jpy ?? 0;
                  return (
                    <tr key={d.slot_start} className="align-middle">
                      <td className="px-2 py-1 font-mono text-xs text-muted-foreground">
                        {new Date(d.slot_start).toISOString().slice(11, 16)}
                      </td>
                      {REGIMES.map((reg) => {
                        const p = rs ? (reg === "base" ? rs.p_base : reg === "spike" ? rs.p_spike : rs.p_drop) : 0;
                        const v = pnl * p;
                        return (
                          <td
                            key={reg}
                            title={`p=${p.toFixed(2)}, pnl=¥${pnl.toFixed(0)}`}
                            className="px-2 py-1 text-center"
                            style={{ backgroundColor: colorForValue(v, vMax), color: "white" }}
                          >
                            {rs ? `¥${Math.round(v).toLocaleString()}` : "—"}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
