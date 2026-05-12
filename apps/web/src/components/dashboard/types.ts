/**
 * Shared types for the dashboard page + its client component. Living here
 * (not in the Server Component page file) avoids a circular type-import
 * cycle that can confuse Next 14's dev compiler.
 */

export type LatestRun = {
  kind: string;
  status: string;
  created_at: string;
  duration_ms: number | null;
  error: string | null;
  output: Record<string, unknown> | null;
};

export type DataSpan = {
  kind: string;
  table: string;
  min: string | null;
  max: string | null;
  row_count: number;
};
