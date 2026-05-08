"use client";

/**
 * /workbench — M7 LSM valuation runner.
 *
 * Two-pane layout: AssetForm on the left, ValuationResults on the right.
 * Submitting the form POSTs to `/api/value-asset`, which inserts the
 * valuations row and kicks the Modal endpoint. The right pane subscribes
 * to that valuations row via Realtime and renders progressively as the
 * status transitions queued → running → done.
 */

import { useState } from "react";

import { AssetForm } from "@/components/workbench/AssetForm";
import { ValuationResults } from "@/components/workbench/ValuationResults";

export default function WorkbenchPage() {
  const [valuationId, setValuationId] = useState<string | null>(null);

  return (
    <main className="mx-auto max-w-7xl px-6 py-12">
      <header className="mb-10">
        <h1 className="text-3xl font-semibold tracking-tight">Workbench</h1>
        <p className="mt-2 text-sm text-neutral-500">
          Configure a storage asset and run a Boogert-de Jong LSM valuation
          against the latest forecast paths. Results stream in live via
          Supabase Realtime.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <AssetForm onValuationQueued={setValuationId} />
        <ValuationResults valuationId={valuationId} />
      </div>
    </main>
  );
}
