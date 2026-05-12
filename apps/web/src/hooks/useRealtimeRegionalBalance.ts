"use client";

import { useCallback, useEffect, useState } from "react";

import { createBrowserClient } from "@/lib/supabase/client";

import type { RegionalBalance } from "@/app/api/regional-balance/route";

const REFRESH_MS = 30 * 60 * 1000; // 30 minutes

/**
 * Fetches /api/regional-balance, then keeps it fresh via:
 *  - 30-minute setInterval heartbeat
 *  - Realtime INSERT subscription on demand_actuals so a fresh ingest cron
 *    refreshes the page within seconds
 */
export function useRealtimeRegionalBalance() {
  const [rows, setRows] = useState<RegionalBalance[]>([]);
  const [slotStart, setSlotStart] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);

  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch("/api/regional-balance")
      .then(async (r) => {
        const j = await r.json();
        if (!r.ok) throw new Error(j?.error?.toString() ?? r.statusText);
        return j as { slot_start: string | null; rows: RegionalBalance[] };
      })
      .then((j) => {
        if (cancelled) return;
        setRows(j.rows);
        setSlotStart(j.slot_start);
        setFetchedAt(new Date());
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
        // eslint-disable-next-line no-console
        console.error("regional-balance fetch failed:", e);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  // 30-minute heartbeat.
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  // Realtime: new demand row → refetch immediately.
  useEffect(() => {
    let supa;
    try {
      supa = createBrowserClient();
    } catch {
      return;
    }
    // Unique channel name per mount — React Strict Mode double-invokes the
    // effect in dev and Supabase Realtime rejects `.on()` calls on a channel
    // name that was already subscribed.
    const channelName = `dashboard-regional-balance-${Math.random().toString(36).slice(2)}`;
    const channel = supa.channel(channelName);
    channel.on(
      "postgres_changes",
      { event: "INSERT", schema: "public", table: "demand_actuals" },
      () => setTick((n) => n + 1),
    );
    channel.subscribe();
    return () => {
      supa.removeChannel(channel);
    };
  }, []);

  return { rows, slotStart, loading, error, refresh, fetchedAt };
}
