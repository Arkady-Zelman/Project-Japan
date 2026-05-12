"use client";

/**
 * Compute-runs status table — Client Component.
 *
 * Generalizes the older IngestStatusTable: shows last-run rows for any group
 * of compute_runs kinds (ingest_*, stack_*, regime_*, vlstm_*, lsm_*,
 * backtest, …). Subscribes to compute_runs INSERT/UPDATE via Realtime and
 * patches the local snapshot in place.
 *
 * Data-span column is shown only when the caller passes a non-empty
 * `dataSpans` map; model + compute groups omit it.
 */

import { useEffect, useMemo, useState } from "react";

import { createBrowserClient } from "@/lib/supabase/client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import type { DataSpan, LatestRun } from "@/components/dashboard/types";

type Props = {
  title: string;
  description: string;
  kinds: string[];
  initialRuns: LatestRun[];
  dataSpans?: DataSpan[];
};

type Status = "ok" | "running" | "failed" | "missing";

function computeStatus(run: LatestRun | undefined): Status {
  if (!run) return "missing";
  if (run.status === "done") return "ok";
  if (run.status === "running" || run.status === "queued") return "running";
  return "failed";
}

function statusBadge(status: Status) {
  const label =
    status === "ok"
      ? "OK"
      : status === "running"
        ? "Running"
        : status === "failed"
          ? "Failed"
          : "Never run";
  const tone =
    status === "ok"
      ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
      : status === "running"
        ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
        : status === "failed"
          ? "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
          : "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-400";
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
      {label}
    </span>
  );
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  const now = Date.now();
  const diffSec = Math.round((now - t) / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
  return `${Math.round(diffSec / 86400)}d ago`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toISOString().slice(0, 10);
}

export function ComputeRunsTable({ title, description, kinds, initialRuns, dataSpans }: Props) {
  const [runs, setRuns] = useState<LatestRun[]>(initialRuns);
  const showSpan = (dataSpans?.length ?? 0) > 0;
  const kindSet = useMemo(() => new Set(kinds), [kinds]);

  useEffect(() => {
    let supa;
    try {
      supa = createBrowserClient();
    } catch {
      return;
    }
    const channel = supa
      .channel(`dashboard-${title.toLowerCase().replace(/\s+/g, "-")}-${Math.random().toString(36).slice(2)}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "compute_runs" },
        (payload) => {
          const row = payload.new as LatestRun;
          if (!row.kind || !kindSet.has(row.kind)) return;
          setRuns((prev) => {
            const filtered = prev.filter((r) => r.kind !== row.kind);
            return [row, ...filtered];
          });
        }
      )
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "compute_runs" },
        (payload) => {
          const row = payload.new as LatestRun;
          if (!row.kind || !kindSet.has(row.kind)) return;
          setRuns((prev) => prev.map((r) => (r.kind === row.kind ? { ...r, ...row } : r)));
        }
      )
      .subscribe();
    return () => {
      supa.removeChannel(channel);
    };
  }, [title, kindSet]);

  const byKind = useMemo(() => {
    const m = new Map<string, LatestRun>();
    for (const r of runs) {
      const existing = m.get(r.kind);
      if (!existing || new Date(r.created_at) > new Date(existing.created_at)) m.set(r.kind, r);
    }
    return m;
  }, [runs]);

  const spansByKind = useMemo(() => {
    const m = new Map<string, DataSpan>();
    for (const s of dataSpans ?? []) m.set(s.kind, s);
    return m;
  }, [dataSpans]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0 sm:p-0">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-50 text-xs uppercase tracking-wide text-neutral-500 dark:bg-neutral-900/50 dark:text-neutral-400">
            <tr>
              <th className="px-4 py-3 font-medium">Kind</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Last run</th>
              <th className="px-4 py-3 font-medium text-right">Duration</th>
              <th className="px-4 py-3 font-medium">Last output</th>
              {showSpan && <th className="px-4 py-3 font-medium">Data span</th>}
              {showSpan && <th className="px-4 py-3 font-medium text-right">Rows</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {kinds.map((kind) => {
              const run = byKind.get(kind);
              const span = spansByKind.get(kind);
              const status = computeStatus(run);
              const out = run?.output ?? null;
              const inserted = (out?.["rows_inserted"] as number | undefined) ?? null;
              const notes = (out?.["notes"] as string | null | undefined) ?? null;
              return (
                <tr key={kind} className="align-top">
                  <td className="px-4 py-3 font-mono text-xs text-neutral-700 dark:text-neutral-300">
                    {kind}
                  </td>
                  <td className="px-4 py-3">{statusBadge(status)}</td>
                  <td
                    className="px-4 py-3 text-neutral-700 dark:text-neutral-300"
                    suppressHydrationWarning
                  >
                    {relativeTime(run?.created_at ?? null)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-neutral-500">
                    {run?.duration_ms != null ? `${run.duration_ms} ms` : "—"}
                  </td>
                  <td className="px-4 py-3 text-neutral-600 dark:text-neutral-400">
                    {run?.error ? (
                      <span className="text-red-600 dark:text-red-400">
                        {(run.error.split("\n")[0] ?? run.error).slice(0, 100)}
                      </span>
                    ) : notes ? (
                      <span className="italic">{notes.slice(0, 120)}</span>
                    ) : inserted != null ? (
                      <span>{inserted} rows touched</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  {showSpan && (
                    <td className="px-4 py-3 text-neutral-700 dark:text-neutral-300">
                      {span && span.min ? `${formatDate(span.min)} → ${formatDate(span.max)}` : "—"}
                    </td>
                  )}
                  {showSpan && (
                    <td className="px-4 py-3 text-right tabular-nums text-neutral-500">
                      {span ? span.row_count.toLocaleString() : "—"}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
