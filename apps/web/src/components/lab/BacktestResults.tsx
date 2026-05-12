"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useRealtimeBacktest, type BacktestRow, type TradeRow } from "@/hooks/useRealtimeBacktest";

const STRATEGY_COLORS: Record<string, string> = {
  naive_spread: "#9333ea",       // purple
  intrinsic: "#22c55e",          // green
  rolling_intrinsic: "#3b82f6",  // blue
  lsm: "#dc2626",                // red
};

const STRATEGY_LABELS: Record<string, string> = {
  naive_spread: "Naive spread",
  intrinsic: "Intrinsic",
  rolling_intrinsic: "Rolling intrinsic",
  lsm: "LSM (stack)",
};

type Props = {
  backtestIds: string[];
};

const fmtJpy = (v: number | null | undefined): string => {
  if (v == null) return "—";
  if (Math.abs(v) >= 1_000_000) return `¥${(v / 1_000_000).toFixed(2)}M`;
  if (Math.abs(v) >= 1_000) return `¥${(v / 1_000).toFixed(0)}K`;
  return `¥${v.toFixed(0)}`;
};

const fmtNum = (v: number | null | undefined, dp = 2): string =>
  v == null ? "—" : v.toFixed(dp);

export function BacktestResults({ backtestIds }: Props) {
  const { rows, loading, error } = useRealtimeBacktest(backtestIds);

  // Build merged equity-curve dataset: one row per timestamp, columns
  // for each strategy's cumulative cash.
  const equityCurveData = useMemo(() => {
    const tsSet = new Set<number>();
    const perStrategy: Record<string, Map<number, number>> = {};
    for (const row of rows) {
      if (!row.trades_jsonb || row.status !== "done") continue;
      const m = new Map<number, number>();
      for (const t of row.trades_jsonb as TradeRow[]) {
        const ts = new Date(t.ts).getTime();
        m.set(ts, t.cum_jpy);
        tsSet.add(ts);
      }
      perStrategy[row.strategy] = m;
    }
    if (tsSet.size === 0) return [];
    const sorted = Array.from(tsSet).sort();
    return sorted.map((ts) => {
      const point: Record<string, number | null> = { ts };
      for (const [strategy, m] of Object.entries(perStrategy)) {
        point[strategy] = m.get(ts) ?? null;
      }
      return point;
    });
  }, [rows]);

  // Modelled vs realised P&L bar pairs.
  const pnlBarData = useMemo(() => {
    return rows.map((r) => ({
      name: STRATEGY_LABELS[r.strategy] ?? r.strategy,
      strategy: r.strategy,
      realised: r.realised_pnl_jpy ?? 0,
      modelled: r.modelled_pnl_jpy ?? 0,
      slippage: r.slippage_jpy ?? 0,
    }));
  }, [rows]);

  if (!backtestIds.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Strategy comparison</CardTitle>
          <CardDescription>
            Configure a backtest on the left and click Run. Up to four
            strategies stream in via Supabase Realtime as Modal computes
            them in parallel.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (loading && !rows.length) {
    return (
      <Card>
        <CardHeader><CardTitle>Loading…</CardTitle></CardHeader>
      </Card>
    );
  }
  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Error</CardTitle>
          <CardDescription className="text-red-600">{error}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Comparison table */}
      <Card>
        <CardHeader>
          <CardTitle>Strategy comparison</CardTitle>
          <CardDescription>
            Realised P&L = modelled − slippage. Sharpe is annualised on
            daily returns. Max DD is the worst peak-to-trough loss in JPY
            on the cumulative equity curve.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase text-muted-foreground">
                  <th className="py-2 pr-3">Strategy</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Realised P&L</th>
                  <th className="py-2 pr-3">Modelled P&L</th>
                  <th className="py-2 pr-3">Slippage</th>
                  <th className="py-2 pr-3">Sharpe</th>
                  <th className="py-2 pr-3">Max DD</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const leaderId = rows
                    .filter((r) => r.status === "done" && r.realised_pnl_jpy != null)
                    .sort((a, b) => (b.realised_pnl_jpy ?? 0) - (a.realised_pnl_jpy ?? 0))[0]?.id;
                  return rows.map((r) => (
                    <tr key={r.id} className="border-b">
                      <td className="py-2 pr-3 font-medium" style={{ color: STRATEGY_COLORS[r.strategy] }}>
                        <span className="inline-flex items-center gap-2">
                          {STRATEGY_LABELS[r.strategy] ?? r.strategy}
                          {leaderId === r.id && (
                            <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                              Leader
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="py-2 pr-3">
                        <StatusBadge status={r.status} />
                      </td>
                      <td className="py-2 pr-3 font-mono">{fmtJpy(r.realised_pnl_jpy)}</td>
                      <td className="py-2 pr-3 font-mono text-muted-foreground">{fmtJpy(r.modelled_pnl_jpy)}</td>
                      <td className="py-2 pr-3 font-mono text-orange-600">{fmtJpy(r.slippage_jpy)}</td>
                      <td className="py-2 pr-3 font-mono">{fmtNum(r.sharpe)}</td>
                      <td className="py-2 pr-3 font-mono text-red-700">{fmtJpy(r.max_drawdown_jpy)}</td>
                    </tr>
                  ));
                })()}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Equity curves */}
      {equityCurveData.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Equity curves</CardTitle>
            <CardDescription>
              Cumulative realised P&L over the backtest window for each strategy.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={equityCurveData} margin={{ bottom: 56 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis
                    type="number"
                    dataKey="ts"
                    domain={["dataMin", "dataMax"]}
                    scale="time"
                    tick={{ fontSize: 10, fill: "#a3a3a3" }}
                    angle={-90}
                    textAnchor="end"
                    height={56}
                    tickFormatter={(t) => {
                      const d = new Date(t as number);
                      const mo = String(d.getMonth() + 1).padStart(2, "0");
                      const dd = String(d.getDate()).padStart(2, "0");
                      const hh = String(d.getHours()).padStart(2, "0");
                      const mm = String(d.getMinutes()).padStart(2, "0");
                      return `${mo}-${dd} ${hh}:${mm}`;
                    }}
                  />
                  <YAxis
                    tickFormatter={(v) => fmtJpy(typeof v === "number" ? v : Number(v))}
                  />
                  <ReTooltip
                    labelFormatter={(t) => new Date(t as number).toLocaleString("ja-JP")}
                    formatter={(value, name) => [
                      fmtJpy(typeof value === "number" ? value : Number(value)),
                      STRATEGY_LABELS[String(name)] ?? String(name),
                    ]}
                  />
                  <Legend
                    verticalAlign="top"
                    align="center"
                    height={32}
                    wrapperStyle={{ paddingBottom: 8, fontSize: 11 }}
                    formatter={(v) => STRATEGY_LABELS[String(v)] ?? String(v)}
                  />
                  {Object.keys(STRATEGY_COLORS).map((s) => (
                    <Line
                      key={s}
                      type="monotone"
                      dataKey={s}
                      stroke={STRATEGY_COLORS[s]}
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                      connectNulls
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Modelled vs realised + slippage */}
      {pnlBarData.length > 0 && pnlBarData.some((p) => p.realised !== 0) && (
        <Card>
          <CardHeader>
            <CardTitle>Modelled vs realised P&L</CardTitle>
            <CardDescription>
              Bar pair per strategy: modelled (mid-price, no slippage) minus
              the orange slippage cost = realised. Highlights how much the
              ¥/kWh half-spread eats into each strategy.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={pnlBarData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="name" />
                  <YAxis tickFormatter={(v) => fmtJpy(typeof v === "number" ? v : Number(v))} />
                  <ReTooltip
                    formatter={(value) =>
                      fmtJpy(typeof value === "number" ? value : Number(value))
                    }
                  />
                  <Legend />
                  <Bar dataKey="realised" name="Realised" isAnimationActive={false}>
                    {pnlBarData.map((d, i) => (
                      <Cell key={i} fill={STRATEGY_COLORS[d.strategy] ?? "#3b82f6"} />
                    ))}
                  </Bar>
                  <Bar dataKey="slippage" name="Slippage" fill="#f97316" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: BacktestRow["status"] }) {
  const colour =
    status === "done" ? "bg-emerald-100 text-emerald-700"
      : status === "failed" ? "bg-red-100 text-red-700"
      : status === "running" ? "bg-blue-100 text-blue-700"
      : "bg-neutral-100 text-neutral-700";
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${colour}`}>
      {status}
    </span>
  );
}
