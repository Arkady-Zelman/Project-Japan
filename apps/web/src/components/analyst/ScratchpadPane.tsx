"use client";

import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { type AgentArtifact } from "@/hooks/useChatSession";

import { PlotlyArtifact } from "./PlotlyArtifact";

type Props = {
  artifacts: AgentArtifact[];
};

const TYPE_LABELS: Record<string, string> = {
  chart: "Charts",
  query_result: "Queries",
  model_spec: "Models",
};

export function ScratchpadPane({ artifacts }: Props) {
  const [filter, setFilter] = useState<"all" | "chart" | "query_result" | "model_spec">("all");
  const filtered = filter === "all" ? artifacts : artifacts.filter((a) => a.type === filter);

  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <CardTitle>Scratchpad</CardTitle>
        <CardDescription>
          Charts, queries, and model artifacts the analyst created during this session.
        </CardDescription>
        <div className="mt-2 flex gap-2 text-xs">
          {(["all", "chart", "query_result", "model_spec"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setFilter(t)}
              className={`rounded-md px-2 py-1 ${
                filter === t
                  ? "bg-primary text-primary-foreground"
                  : "border border-input bg-background"
              }`}
            >
              {t === "all" ? "All" : TYPE_LABELS[t]}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto space-y-4">
        {filtered.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No artifacts yet. Ask the analyst to chart or query something.
          </p>
        )}
        {filtered.map((a) => (
          <div key={a.id} className="rounded-md border border-input bg-background p-3">
            <div className="mb-2 flex items-baseline justify-between">
              <p className="text-sm font-medium">{a.title ?? "(untitled)"}</p>
              <span className="text-xs text-muted-foreground">
                {a.type} · {new Date(a.created_at).toLocaleTimeString("ja-JP")}
              </span>
            </div>
            {a.type === "chart" && <PlotlyArtifact spec={a.spec_jsonb} />}
            {a.type === "query_result" && <QueryResultArtifact spec={a.spec_jsonb} />}
            {a.type === "model_spec" && <ModelSpecArtifact spec={a.spec_jsonb} />}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function QueryResultArtifact({ spec }: { spec: Record<string, unknown> }) {
  const cols = (spec.columns as string[] | undefined) ?? [];
  const rows = (spec.rows as unknown[][] | undefined) ?? [];
  const truncated = Boolean(spec.truncated);
  return (
    <div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b">
            {cols.map((c) => (
              <th key={c} className="px-2 py-1 text-left">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 50).map((r, i) => (
            <tr key={i} className="border-b">
              {r.map((v, j) => (
                <td key={j} className="px-2 py-1 font-mono">{String(v)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {(rows.length > 50 || truncated) && (
        <p className="mt-1 text-xs text-muted-foreground">
          Showing first 50 of {rows.length}{truncated ? " (truncated by query_data)" : ""}.
        </p>
      )}
    </div>
  );
}

function ModelSpecArtifact({ spec }: { spec: Record<string, unknown> }) {
  return (
    <pre className="overflow-x-auto rounded bg-neutral-50 p-2 text-xs dark:bg-neutral-900">
      {JSON.stringify(spec, null, 2)}
    </pre>
  );
}
