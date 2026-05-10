"use client";

import dynamic from "next/dynamic";

/**
 * PlotlyArtifact — renders an agent_artifacts.spec_jsonb (Plotly figure
 * spec: { data, layout }) using react-plotly.js bound to plotly.js-basic-dist
 * for a small bundle footprint.
 *
 * The plotly bundle is lazy-loaded so the analyst page first paint isn't
 * delayed by the ~700 KB chart engine.
 */

// react-plotly.js's `Plot` component types are loose enough that we treat
// the dynamic import as `any`. The runtime accepts any data + layout dict
// — which is exactly the agent_artifacts.spec_jsonb format.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Plot = dynamic<any>(
  async () => {
    // @ts-expect-error plotly.js-basic-dist ships without TS types.
    const Plotly = (await import("plotly.js-basic-dist")).default;
    const createPlotlyComponent = (await import("react-plotly.js/factory")).default;
    return createPlotlyComponent(Plotly);
  },
  { ssr: false, loading: () => <div className="text-xs text-muted-foreground">loading chart…</div> },
);

export function PlotlyArtifact({ spec }: { spec: Record<string, unknown> }) {
  const data = Array.isArray(spec.data) ? spec.data : [];
  const layout = (spec.layout ?? {}) as Record<string, unknown>;
  const layoutMerged = {
    ...layout,
    autosize: true,
    margin: { l: 50, r: 30, t: 40, b: 40, ...((layout.margin as object) ?? {}) },
  };
  const config = (spec.config ?? {}) as Record<string, unknown>;
  const configMerged = { responsive: true, displaylogo: false, ...config };

  return (
    <Plot
      data={data}
      layout={layoutMerged}
      config={configMerged}
      useResizeHandler
      style={{ width: "100%", height: "320px" }}
    />
  );
}
