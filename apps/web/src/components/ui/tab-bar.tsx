"use client";

/**
 * Page-level tab bar. A flat horizontal strip of buttons that swaps a single
 * content panel below. Deliberately bypasses the shadcn `Tabs` primitive —
 * the base-ui orientation/flex-direction behaviour was inconsistent with the
 * dashboard's full-width layout requirement.
 */

import { cn } from "@/lib/utils";

export type TabBarItem<T extends string = string> = {
  value: T;
  label: React.ReactNode;
};

export function TabBar<T extends string = string>({
  value,
  onValueChange,
  items,
  children,
  className,
}: {
  value: T;
  onValueChange: (next: T) => void;
  items: ReadonlyArray<TabBarItem<T>>;
  children: (active: T) => React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-6", className)}>
      <div
        role="tablist"
        aria-orientation="horizontal"
        className="flex w-full items-center gap-1 border-b border-foreground/10"
      >
        {items.map((item) => {
          const active = item.value === value;
          return (
            <button
              key={item.value}
              role="tab"
              type="button"
              aria-selected={active}
              onClick={() => onValueChange(item.value)}
              className={cn(
                "relative -mb-px border-b-2 px-3 py-2 text-sm font-medium transition",
                active
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      <div role="tabpanel">{children(value)}</div>
    </div>
  );
}
