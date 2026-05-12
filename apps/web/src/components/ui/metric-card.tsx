import { cn } from "@/lib/utils";

/**
 * Small KPI card: label + large value + unit suffix.
 * Used in the page-header metric strip and inside expanded region detail.
 */
export function MetricCard({
  label,
  value,
  unit,
  hint,
  tone = "neutral",
  className,
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  hint?: React.ReactNode;
  tone?: "neutral" | "positive" | "negative" | "warning";
  className?: string;
}) {
  const toneClass =
    tone === "positive"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "negative"
        ? "text-red-600 dark:text-red-400"
        : tone === "warning"
          ? "text-amber-600 dark:text-amber-400"
          : "text-foreground";
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl px-4 py-3",
        "bg-[linear-gradient(180deg,rgba(255,255,255,0.10)_0%,rgba(255,255,255,0.025)_22%,transparent_60%),rgba(30,32,40,0.36)]",
        "backdrop-blur-[28px] backdrop-saturate-[1.45]",
        "shadow-[inset_0_1px_0_rgba(255,255,255,0.14),inset_0_0_0_1px_rgba(255,255,255,0.08)]",
        "before:absolute before:left-0 before:top-3.5 before:bottom-3.5 before:w-0.5 before:rounded-sm",
        "before:bg-gradient-to-b before:from-blue-500/55 before:to-transparent",
        className,
      )}
    >
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={cn("text-2xl font-semibold tabular-nums", toneClass)}>
          {value}
        </span>
        {unit && <span className="text-xs text-muted-foreground">{unit}</span>}
      </div>
      {hint && (
        <div className="mt-1 text-xs text-muted-foreground">{hint}</div>
      )}
    </div>
  );
}
