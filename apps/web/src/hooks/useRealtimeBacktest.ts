"use client";

import { useEffect, useState } from "react";

import { createBrowserClient } from "@/lib/supabase/client";

/**
 * Subscribes to a list of `backtests` rows (one per strategy in a single
 * "Run backtest" submission). Returns the latest snapshot. Refetches on
 * every postgres-changes event for any of the rows.
 */

export type BacktestRow = {
  id: string;
  asset_id: string;
  user_id: string;
  strategy: "lsm" | "intrinsic" | "rolling_intrinsic" | "naive_spread";
  window_start: string;
  window_end: string;
  status: "queued" | "running" | "done" | "failed";
  realised_pnl_jpy: number | null;
  modelled_pnl_jpy: number | null;
  slippage_jpy: number | null;
  sharpe: number | null;
  max_drawdown_jpy: number | null;
  trades_jsonb: TradeRow[] | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

export type TradeRow = {
  ts: string;
  soc_mwh: number;
  action_mw: number;
  mid_jpy_kwh: number;
  cash_jpy: number;
  cum_jpy: number;
};

export function useRealtimeBacktest(backtestIds: string[]): {
  rows: BacktestRow[];
  loading: boolean;
  error: string | null;
} {
  const [rows, setRows] = useState<BacktestRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!backtestIds.length) {
      setRows([]);
      return;
    }
    const supabase = createBrowserClient();

    const fetchAll = async () => {
      const { data, error: fe } = await supabase
        .from("backtests")
        .select("*")
        .in("id", backtestIds)
        .order("created_at", { ascending: true });
      if (fe) {
        setError(fe.message);
        return;
      }
      setRows((data ?? []) as BacktestRow[]);
    };

    setLoading(true);
    setError(null);
    fetchAll().finally(() => setLoading(false));

    // Subscribe to changes on each id (we use a single channel with multiple filters).
    const channel = supabase.channel(`backtests:${backtestIds.join(",")}:${Math.random().toString(36).slice(2)}`);
    for (const id of backtestIds) {
      channel.on(
        "postgres_changes",
        { event: "*", schema: "public", table: "backtests", filter: `id=eq.${id}` },
        () => {
          fetchAll();
        },
      );
    }
    channel.subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [backtestIds.join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps

  return { rows, loading, error };
}
