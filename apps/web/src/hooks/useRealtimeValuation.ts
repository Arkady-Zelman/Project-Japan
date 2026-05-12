"use client";

import { useEffect, useState } from "react";

import { createBrowserClient } from "@/lib/supabase/client";

/**
 * Subscribes to a single `valuations` row + its `valuation_decisions`.
 *
 * Returns the latest snapshot. Refetches on every postgres-changes event for
 * the row. Per BUILD_SPEC §6.4: the workbench renders progressively as the
 * Modal LSM transitions queued → running → done.
 */

export type ValuationRow = {
  id: string;
  asset_id: string;
  user_id: string;
  forecast_run_id: string | null;
  method: string;
  status: "queued" | "running" | "done" | "failed";
  horizon_start: string;
  horizon_end: string;
  intrinsic_value_jpy: number | null;
  extrinsic_value_jpy: number | null;
  total_value_jpy: number | null;
  ci_lower_jpy: number | null;
  ci_upper_jpy: number | null;
  n_paths: number | null;
  n_volume_grid: number | null;
  runtime_seconds: number | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

export type DecisionRow = {
  valuation_id: string;
  slot_start: string;
  soc_mwh: number | null;
  action_mw: number | null;
  expected_pnl_jpy: number | null;
};

export function useRealtimeValuation(valuation_id: string | null): {
  valuation: ValuationRow | null;
  decisions: DecisionRow[];
  loading: boolean;
  error: string | null;
} {
  const [valuation, setValuation] = useState<ValuationRow | null>(null);
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!valuation_id) {
      setValuation(null);
      setDecisions([]);
      return;
    }
    const supabase = createBrowserClient();

    const fetchAll = async () => {
      const { data: vRow, error: vErr } = await supabase
        .from("valuations")
        .select("*")
        .eq("id", valuation_id)
        .maybeSingle();
      if (vErr) {
        setError(vErr.message);
        return;
      }
      setValuation((vRow as ValuationRow | null) ?? null);

      // Pull decisions too — only meaningful once the LSM has populated them.
      if (vRow && (vRow as ValuationRow).status !== "queued") {
        const { data: dRows } = await supabase
          .from("valuation_decisions")
          .select("*")
          .eq("valuation_id", valuation_id)
          .order("slot_start", { ascending: true });
        setDecisions((dRows ?? []) as DecisionRow[]);
      } else {
        setDecisions([]);
      }
    };

    setLoading(true);
    setError(null);
    fetchAll().finally(() => setLoading(false));

    // Realtime subscription on the valuations row.
    const channel = supabase
      .channel(`valuation:${valuation_id}:${Math.random().toString(36).slice(2)}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "valuations", filter: `id=eq.${valuation_id}` },
        () => {
          fetchAll();
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [valuation_id]);

  return { valuation, decisions, loading, error };
}
