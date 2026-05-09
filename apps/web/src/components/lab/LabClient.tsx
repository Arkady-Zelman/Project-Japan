"use client";

/**
 * Two-pane Client Component for /lab. Left: BacktestForm (asset picker +
 * dates + strategies). Right: BacktestResults (subscribes to backtests
 * rows via Supabase Realtime).
 */

import { useState } from "react";

import { BacktestForm } from "@/components/lab/BacktestForm";
import { BacktestResults } from "@/components/lab/BacktestResults";

type AssetOption = {
  id: string;
  name: string;
  area_code: string;
  power_mw: number;
  energy_mwh: number;
  created_at: string;
};

type Props = {
  assets: AssetOption[];
};

export function LabClient({ assets }: Props) {
  const [backtestIds, setBacktestIds] = useState<string[]>([]);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <BacktestForm assets={assets} onBacktestsQueued={setBacktestIds} />
      <BacktestResults backtestIds={backtestIds} />
    </div>
  );
}
