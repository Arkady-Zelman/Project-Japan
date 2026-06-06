"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  ComposedChart,
  CartesianGrid,
  Line,
  ReferenceLine,
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
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { captureEvent } from "@/lib/posthog";
import { useRealtimeForecast } from "@/hooks/useRealtimeForecast";
import { useLanguage } from "@/lib/i18n/LanguageProvider";
import type { TranslationKey } from "@/lib/i18n/dictionary";

const AREA_CODES = ["TK", "HK", "TH", "CB", "HR", "KS", "CG", "SK", "KY"] as const;
type AreaCode = (typeof AREA_CODES)[number];

const SELECT_CLS =
  "w-full appearance-none rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring";

const REGIME_COLOR = {
  base: "rgba(34, 197, 94, 0.10)",     // green-500/10
  spike: "rgba(220, 38, 38, 0.15)",    // red-600/15
  drop: "rgba(14, 165, 233, 0.10)",    // sky-500/10
} as const;

type Slot = {
  slot_start: string;
  mean: number;
  p05: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
  stack: number | null;
  regime: "base" | "spike" | "drop" | null;
};

type ForecastResponse = {
  area: { id: string; code: string; name_en: string };
  run: { id: string; forecast_origin: string; n_paths: number } | null;
  slots: Slot[];
  note?: string;
};

export function ForecastPanel() {
  const [area, setArea] = useState<AreaCode>("TK");
  const [withStack, setWithStack] = useState<boolean>(false);
  const [withRegime, setWithRegime] = useState<boolean>(false);
  const [data, setData] = useState<ForecastResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { t, lang } = useLanguage();
  const locale = lang === "ja" ? "ja-JP" : "en-US";

  // Refetch when a new forecast_run lands for this area (M10C L8).
  const realtimeTick = useRealtimeForecast(area);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      area,
      withStack: String(withStack),
      withRegime: String(withRegime),
    });
    fetch(`/api/forecast-paths?${params}`)
      .then(async (r) => {
        const j = await r.json();
        if (!r.ok) throw new Error(j?.error?.toString() ?? r.statusText);
        return j as ForecastResponse;
      })
      .then((d) => {
        setData(d);
        captureEvent("forecast_viewed", { area, with_stack: withStack, with_regime: withRegime });
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [area, withStack, withRegime, realtimeTick]);

  const chartData = useMemo(() => {
    if (!data?.slots) return [];
    return data.slots.map((s) => ({
      ts: new Date(s.slot_start).getTime(),
      // For ribbons we need the heights ABOVE the base line, since recharts
      // stacks `Area` components additively. We feed two pairs:
      //   ribbon 5–95 = (low=p05, height=p95-p05)
      //   ribbon 25–75 = (low=p25, height=p75-p25)
      lo90: s.p05,
      hi90: s.p95 - s.p05,
      lo50: s.p25,
      hi50: s.p75 - s.p25,
      mean: s.mean,
      stack: s.stack ?? undefined,
      regime: s.regime,
    }));
  }, [data]);

  const regimeBands = useMemo(() => {
    // Build contiguous coloured bands based on most_likely_regime per slot.
    if (!withRegime || !data?.slots?.length) return [];
    const bands: { from: number; to: number; regime: "base" | "spike" | "drop" }[] = [];
    let cur: { from: number; to: number; regime: "base" | "spike" | "drop" } | null = null;
    for (const s of data.slots) {
      const t = new Date(s.slot_start).getTime();
      if (!s.regime) {
        if (cur) {
          bands.push(cur);
          cur = null;
        }
        continue;
      }
      if (cur && cur.regime === s.regime) {
        cur.to = t;
      } else {
        if (cur) bands.push(cur);
        cur = { from: t, to: t, regime: s.regime };
      }
    }
    if (cur) bands.push(cur);
    return bands;
  }, [withRegime, data]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("forecast.title")}</CardTitle>
        <CardDescription>
          {t("forecast.description.prefix")}{" "}
          <span className="font-mono">most_likely_regime</span>.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t("forecast.area")}
            </label>
            <select
              className={SELECT_CLS}
              value={area}
              onChange={(e) => setArea(e.target.value as AreaCode)}
            >
              {AREA_CODES.map((code) => (
                <option key={code} value={code}>
                  {t(`region.${code}` as TranslationKey)} ({code})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t("forecast.overlayStack")}
            </label>
            <label className="flex items-center gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-sm">
              <input
                type="checkbox"
                checked={withStack}
                onChange={(e) => setWithStack(e.target.checked)}
              />
              <span>{t("forecast.showStack")}</span>
            </label>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t("forecast.colorByRegime")}
            </label>
            <label className="flex items-center gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-sm">
              <input
                type="checkbox"
                checked={withRegime}
                onChange={(e) => setWithRegime(e.target.checked)}
              />
              <span>{t("forecast.shadeByRegime")}</span>
            </label>
          </div>
        </div>

        <Separator />

        {loading && (
          <div className="space-y-2">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-[320px] w-full" />
          </div>
        )}
        {error && (
          <p className="text-sm text-red-600">
            {t("forecast.errorPrefix")} {error}
          </p>
        )}
        {data?.note && <p className="text-sm text-muted-foreground">{data.note}</p>}

        {data?.run && (
          <div className="text-xs text-muted-foreground">
            {t("forecast.originPrefix")}{" "}
            {new Date(data.run.forecast_origin).toLocaleString(locale)} ·{" "}
            {data.run.n_paths.toLocaleString()} {t("forecast.pathsSuffix")}{" "}
            <span className="font-mono">{data.run.id.slice(0, 8)}</span>
          </div>
        )}

        {chartData.length > 0 ? (
          <div className="h-[320px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 8, right: 24, bottom: 72, left: 56 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  type="number"
                  dataKey="ts"
                  domain={["dataMin", "dataMax"]}
                  scale="time"
                  tick={{ fontSize: 10, fill: "#a3a3a3" }}
                  angle={-90}
                  textAnchor="end"
                  height={64}
                  tickFormatter={(t) => {
                    const d = new Date(t as number);
                    const hh = String(d.getHours()).padStart(2, "0");
                    const mm = String(d.getMinutes()).padStart(2, "0");
                    return `${hh}:${mm}`;
                  }}
                />
                <YAxis
                  tickFormatter={(v) => {
                    const n = typeof v === "number" ? v : Number(v);
                    return Number.isFinite(n) ? `¥${n.toFixed(1)}` : "—";
                  }}
                  label={{
                    value: t("forecast.yAxisLabel"),
                    angle: -90,
                    position: "insideLeft",
                    offset: -38,
                    style: { textAnchor: "middle" },
                  }}
                />
                <ReTooltip
                  labelFormatter={(ts) => new Date(ts as number).toLocaleString(locale)}
                  formatter={(value, name) => {
                    const n = typeof value === "number" ? value : Number(value);
                    if (!Number.isFinite(n)) return ["—", String(name)];
                    return [`¥${n.toFixed(2)}`, String(name)];
                  }}
                />
                {/* 5–95 ribbon: invisible base + visible top */}
                <Area
                  type="monotone"
                  dataKey="lo90"
                  stackId="ribbon90"
                  stroke="none"
                  fill="transparent"
                  isAnimationActive={false}
                  legendType="none"
                />
                <Area
                  type="monotone"
                  dataKey="hi90"
                  stackId="ribbon90"
                  stroke="none"
                  fill="#3b82f6"
                  fillOpacity={0.12}
                  isAnimationActive={false}
                  name={t("forecast.bandLabel90")}
                />
                {/* 25–75 ribbon */}
                <Area
                  type="monotone"
                  dataKey="lo50"
                  stackId="ribbon50"
                  stroke="none"
                  fill="transparent"
                  isAnimationActive={false}
                  legendType="none"
                />
                <Area
                  type="monotone"
                  dataKey="hi50"
                  stackId="ribbon50"
                  stroke="none"
                  fill="#3b82f6"
                  fillOpacity={0.28}
                  isAnimationActive={false}
                  name={t("forecast.bandLabel50")}
                />
                {/* Mean */}
                <Line
                  type="monotone"
                  dataKey="mean"
                  stroke="#1d4ed8"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                  name={t("forecast.meanLabel")}
                />
                {/* Optional stack overlay */}
                {withStack && (
                  <Line
                    type="monotone"
                    dataKey="stack"
                    stroke="#ea580c"
                    strokeDasharray="4 3"
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                    name={t("forecast.stackLabel")}
                    connectNulls
                  />
                )}
                {/* Optional regime shading via ReferenceLine bands */}
                {regimeBands.map((b, i) => (
                  <ReferenceLine
                    key={i}
                    x={(b.from + b.to) / 2}
                    stroke={REGIME_COLOR[b.regime].replace(/0\.\d+/, "0.6")}
                    strokeWidth={Math.max(2, (b.to - b.from) / (1000 * 60 * 30))}
                    strokeOpacity={0.25}
                    ifOverflow="visible"
                  />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        ) : (
          !loading && (
            <p className="text-sm text-muted-foreground">
              {t("forecast.empty.prefix")}{" "}
              <span className="font-mono">python -m vlstm.forecast</span>{" "}
              {t("forecast.empty.middle")}{" "}
              <span className="font-mono">forecast_vlstm_morning</span> /{" "}
              <span className="font-mono">forecast_vlstm_evening</span>{" "}
              {t("forecast.empty.suffix")}
            </p>
          )
        )}
      </CardContent>
    </Card>
  );
}
