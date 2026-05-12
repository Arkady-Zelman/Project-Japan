import { cn } from "@/lib/utils";

/**
 * Page-level hero. Title + supporting paragraph + optional metric strip.
 * Used at the top of /dashboard, /workbench, /lab, /login to anchor the
 * shared aesthetic.
 */
export function PageHeader({
  title,
  description,
  metrics,
  actions,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  metrics?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-8 space-y-4", className)}>
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="bg-gradient-to-b from-white to-slate-300 bg-clip-text text-3xl font-semibold leading-[1.05] tracking-[-0.028em] text-transparent md:text-4xl">
            {title}
          </h1>
          {description && (
            <p className="max-w-3xl text-sm text-muted-foreground">{description}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {metrics && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{metrics}</div>
      )}
    </header>
  );
}
