"use client";

import { useEffect, useState } from "react";

import { createBrowserClient } from "@/lib/supabase/client";

/**
 * Subscribes to forecast_runs INSERT events filtered by area_id.
 * Returns an incrementing counter; consumers re-fetch on change.
 *
 * Spec §10: after twice-daily cron, dashboard fan chart should
 * update without page reload.
 */

export function useRealtimeForecast(areaCode: string | null): number {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!areaCode) return;
    let supa;
    try {
      supa = createBrowserClient();
    } catch {
      return;
    }
    // We don't have area_id (uuid) on the client; subscribe to all
    // forecast_runs INSERTs and let the consumer filter via re-fetch.
    const channel = supa
      .channel(`dashboard-forecast-${areaCode}-${Math.random().toString(36).slice(2)}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "forecast_runs" },
        () => setTick((n) => n + 1),
      )
      .subscribe();
    return () => {
      supa.removeChannel(channel);
    };
  }, [areaCode]);

  return tick;
}
