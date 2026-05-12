"use client";

/**
 * 7-day cron health strip — one row per compute_runs.kind, 7 colored
 * squares (one per day). Green = success, red = failed, grey = no run.
 * Click failed square → modal with the error.
 */

import { useMemo, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export type CronRun = {
  kind: string;
  status: string;
  created_at: string;
  error: string | null;
};

type Props = {
  runs: CronRun[];
  kinds: string[];
};

type DayCell = {
  date: string;
  status: "ok" | "failed" | "missing";
  error: string | null;
};

function dayKey(iso: string): string {
  return iso.slice(0, 10);
}

function buildLastNDays(n: number): string[] {
  const out: string[] = [];
  const today = new Date();
  today.setUTCHours(0, 0, 0, 0);
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(today.getTime() - i * 24 * 60 * 60 * 1000);
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

export function CronHealthStrip({ runs, kinds }: Props) {
  const [open, setOpen] = useState<DayCell | null>(null);
  const days = useMemo(() => buildLastNDays(7), []);
  const byKindDay = useMemo(() => {
    const m = new Map<string, Map<string, CronRun>>();
    for (const r of runs) {
      const k = m.get(r.kind) ?? new Map<string, CronRun>();
      const d = dayKey(r.created_at);
      const existing = k.get(d);
      // Prefer latest per kind+day.
      if (!existing || new Date(r.created_at) > new Date(existing.created_at)) {
        k.set(d, r);
      }
      m.set(r.kind, k);
    }
    return m;
  }, [runs]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cron health (7 days)</CardTitle>
        <CardDescription>
          Per-kind status for each of the last 7 days. Click a red square to see the error.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-left text-xs">
          <thead className="bg-neutral-50 text-xs uppercase tracking-wide text-neutral-500 dark:bg-neutral-900/50 dark:text-neutral-400">
            <tr>
              <th className="px-4 py-2 font-medium">Kind</th>
              {days.map((d) => (
                <th key={d} className="px-2 py-2 font-mono text-[10px]">
                  {d.slice(5)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {kinds.map((kind) => {
              const dayMap = byKindDay.get(kind) ?? new Map<string, CronRun>();
              return (
                <tr key={kind} className="align-middle">
                  <td className="px-4 py-2 font-mono text-xs text-neutral-700 dark:text-neutral-300">
                    {kind}
                  </td>
                  {days.map((d) => {
                    const run = dayMap.get(d);
                    const status: "ok" | "failed" | "missing" = !run
                      ? "missing"
                      : run.status === "done"
                        ? "ok"
                        : run.status === "running" || run.status === "queued"
                          ? "ok"
                          : "failed";
                    const color =
                      status === "ok"
                        ? "bg-green-500"
                        : status === "failed"
                          ? "bg-red-500"
                          : "bg-neutral-300 dark:bg-neutral-700";
                    return (
                      <td key={d} className="px-2 py-2">
                        <button
                          type="button"
                          onClick={() => {
                            if (status === "failed" && run) {
                              setOpen({ date: d, status, error: run.error });
                            }
                          }}
                          disabled={status !== "failed"}
                          className={`h-4 w-6 rounded ${color} ${status === "failed" ? "cursor-pointer" : "cursor-default"}`}
                          title={`${kind} · ${d} · ${status}`}
                        />
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {open && (
          <div className="border-t border-neutral-200 bg-neutral-50 p-4 text-xs dark:border-neutral-800 dark:bg-neutral-900">
            <div className="mb-1 font-medium text-red-700 dark:text-red-300">
              Failed on {open.date}
            </div>
            <pre className="overflow-x-auto whitespace-pre-wrap text-neutral-700 dark:text-neutral-300">
              {open.error ?? "(no error message)"}
            </pre>
            <button
              type="button"
              onClick={() => setOpen(null)}
              className="mt-2 rounded border border-neutral-300 px-2 py-0.5 text-xs hover:bg-neutral-100 dark:border-neutral-700"
            >
              Close
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
