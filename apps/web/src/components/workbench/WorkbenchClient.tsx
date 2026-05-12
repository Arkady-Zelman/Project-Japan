"use client";

import { useState } from "react";

import { AssetForm } from "@/components/workbench/AssetForm";
import { AssetList, type AssetRow } from "@/components/workbench/AssetList";
import { DecisionHeatmap } from "@/components/workbench/DecisionHeatmap";
import { ValuationResults } from "@/components/workbench/ValuationResults";

export function WorkbenchClient() {
  const [valuationId, setValuationId] = useState<string | null>(null);
  const [selected, setSelected] = useState<AssetRow | null>(null);

  return (
    <div className="space-y-6">
      <AssetList onSelect={setSelected} selectedId={selected?.id ?? null} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <AssetForm
          onValuationQueued={setValuationId}
          existingAsset={selected}
          onClearExisting={() => setSelected(null)}
        />
        <ValuationResults valuationId={valuationId} />
      </div>
      {valuationId && <DecisionHeatmap valuationId={valuationId} />}
    </div>
  );
}
