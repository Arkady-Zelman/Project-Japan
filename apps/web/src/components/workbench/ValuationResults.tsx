"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as ReTooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useRealtimeValuation } from "@/hooks/useRealtimeValuation";

const DONUT_COLORS = {
  intrinsic: "#22c55e",   // green-500
  extrinsic: "#3b82f6",   // blue-500
} as const;

const ACTION_CHARGE_COLOR = "#3b82f6";   // blue
const ACTION_DISCHARGE_COLOR = "#dc2626"; // red

type Props = {
  valuationId: string | null;
};

const fmtJpy = (v: number | null | undefined): string => {
  if (v == null) return "—";
  if (Math.abs(v) >= 1_000_000) return `¥${(v / 1_000_000).toFixed(2)}M`;
  if (Math.abs(v) >= 1_000) return `¥${(v / 1_000).toFixed(0)}K`;
  return `¥${v.toFixed(0)}`;
};

const fmtTs = (s: string): string =>
  new Date(s).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });

export function ValuationResults({ valuationId }: Props) {
  const { valuation: v, decisions, loading, error } = useRealtimeValuation(valuationId);

  const donutData = useMemo(() => {
    if (!v?.intrinsic_value_jpy && !v?.extrinsic_value_jpy) return [];
    return [
      { name: "Intrinsic", value: Math.max(0, v.intrinsic_value_jpy ?? 0) },
      { name: "Extrinsic", value: Math.max(0, v.extrinsic_value_jpy ?? 0) },
    ];
  }, [v]);

  const socSeries = useMemo(
    () =>
      decisions.map((d) => ({
        ts: new Date(d.slot_start).getTime(),
        soc: d.soc_mwh ?? null,
      })),
    [decisions],
  );

  const actionSeries = useMemo(
    () =>
      decisions.map((d) => ({
        ts: new Date(d.slot_start).getTime(),
        action: d.action_mw ?? 0,
      })),
    [decisions],
  );

  const pnlSeries = useMemo(
    () =>
      decisions.map((d) => ({
        ts: new Date(d.slot_start).getTime(),
        pnl: d.expected_pnl_jpy ?? 0,
      })),
    [decisions],
  );

  if (!valuationId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Valuation results</CardTitle>
          <CardDescription>
            Configure an asset on the left and click Run valuation. Results
            stream in via Supabase Realtime as the LSM completes.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (loading && !v) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Loading…</CardTitle>
        </CardHeader>
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
  if (!v) return null;

  const status = v.status;

  return (
    <div className="space-y-4">
      {/* Headline numbers + donut */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span>Valuation result</span>
            <StatusBadge status={status} />
          </CardTitle>
          <CardDescription>
            <span className="font-mono">{valuationId.slice(0, 8)}</span> ·{" "}
            {v.n_paths ?? "—"} paths · {v.n_volume_grid ?? "—"} grid points
            {v.runtime_seconds ? ` · ${v.runtime_seconds.toFixed(1)}s` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {status === "queued" && (
            <p className="text-sm text-muted-foreground">
              Queued. The Modal LSM endpoint should pick this up within a few seconds.
            </p>
          )}
          {status === "running" && (
            <p className="text-sm text-blue-700">
              Running on Modal (cpu=4.0). Numba-jitted LSM kernel; expected ~30-60s.
            </p>
          )}
          {status === "failed" && (
            <p className="text-sm text-red-600">Failed: {v.error ?? "(unknown error)"}</p>
          )}
          {status === "done" && (
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div>
                <p className="text-sm text-muted-foreground">Total value</p>
                <p className="text-3xl font-semibold">{fmtJpy(v.total_value_jpy)}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  90% CI: [{fmtJpy(v.ci_lower_jpy)}, {fmtJpy(v.ci_upper_jpy)}]
                </p>
                <div className="mt-3 grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-muted-foreground">
                      <span
                        className="mr-1 inline-block h-2 w-2 rounded"
                        style={{ background: DONUT_COLORS.intrinsic }}
                      />
                      Intrinsic
                    </p>
                    <p className="font-medium">{fmtJpy(v.intrinsic_value_jpy)}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">
                      <span
                        className="mr-1 inline-block h-2 w-2 rounded"
                        style={{ background: DONUT_COLORS.extrinsic }}
                      />
                      Extrinsic
                    </p>
                    <p className="font-medium">{fmtJpy(v.extrinsic_value_jpy)}</p>
                  </div>
                </div>
              </div>
              <div className="h-[200px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={donutData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={50}
                      outerRadius={80}
                      isAnimationActive={false}
                    >
                      {donutData.map((d) => (
                        <Cell
                          key={d.name}
                          fill={
                            d.name === "Intrinsic"
                              ? DONUT_COLORS.intrinsic
                              : DONUT_COLORS.extrinsic
                          }
                        />
                      ))}
                    </Pie>
                    <ReTooltip
                      formatter={(value) =>
                        typeof value === "number" ? fmtJpy(value) : String(value)
                      }
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* SoC envelope */}
      {status === "done" && socSeries.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Expected state of charge</CardTitle>
            <CardDescription>
              Mean SoC over the 48-slot horizon (across paths).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={socSeries}>
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
                    tickFormatter={(t) => fmtTs(new Date(t as number).toISOString())}
                  />
                  <YAxis
                    tickFormatter={(v_) =>
                      `${(typeof v_ === "number" ? v_ : Number(v_)).toFixed(0)}`
                    }
                    label={{
                      value: "MWh",
                      angle: -90,
                      position: "insideLeft",
                      style: { textAnchor: "middle" },
                    }}
                  />
                  <ReTooltip
                    labelFormatter={(t) =>
                      new Date(t as number).toLocaleString("ja-JP")
                    }
                    formatter={(value) =>
                      `${(typeof value === "number" ? value : Number(value)).toFixed(0)} MWh`
                    }
                  />
                  <Line
                    type="monotone"
                    dataKey="soc"
                    stroke="#1d4ed8"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                    name="SoC"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Action timeline + expected p&l */}
      {status === "done" && actionSeries.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Optimal dispatch</CardTitle>
            <CardDescription>
              Mean charge/discharge action per slot (positive = charge, negative
              = discharge). Stack-coloured by direction.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={actionSeries}>
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
                    tickFormatter={(t) => fmtTs(new Date(t as number).toISOString())}
                  />
                  <YAxis
                    tickFormatter={(v_) =>
                      `${(typeof v_ === "number" ? v_ : Number(v_)).toFixed(0)}`
                    }
                    label={{
                      value: "MW",
                      angle: -90,
                      position: "insideLeft",
                      style: { textAnchor: "middle" },
                    }}
                  />
                  <ReTooltip
                    labelFormatter={(t) =>
                      new Date(t as number).toLocaleString("ja-JP")
                    }
                    formatter={(value) =>
                      `${(typeof value === "number" ? value : Number(value)).toFixed(2)} MW`
                    }
                  />
                  <Bar dataKey="action" isAnimationActive={false}>
                    {actionSeries.map((d, i) => (
                      <Cell
                        key={i}
                        fill={
                          d.action >= 0
                            ? ACTION_CHARGE_COLOR
                            : ACTION_DISCHARGE_COLOR
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 h-[150px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={pnlSeries}>
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
                    tickFormatter={(t) => fmtTs(new Date(t as number).toISOString())}
                  />
                  <YAxis
                    tickFormatter={(v_) => fmtJpy(typeof v_ === "number" ? v_ : Number(v_))}
                  />
                  <ReTooltip
                    labelFormatter={(t) =>
                      new Date(t as number).toLocaleString("ja-JP")
                    }
                    formatter={(value) =>
                      fmtJpy(typeof value === "number" ? value : Number(value))
                    }
                  />
                  <Bar dataKey="pnl" fill="#0d9488" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: "queued" | "running" | "done" | "failed" }) {
  const tone =
    status === "done" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
      : status === "failed" ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300"
      : status === "running" ? "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
      : "bg-muted text-muted-foreground";
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${tone}`}>
      {status}
    </span>
  );
}
