/**
 * Translation dictionary for the JEPX-Storage UI.
 *
 * Each entry is keyed by a stable string id with an English and Japanese
 * variant. The English string also acts as the visual fallback when a key
 * is missing from the dictionary.
 */

export type Language = "en" | "ja";

export const LANGUAGES: { code: Language; label: string; nativeLabel: string }[] = [
  { code: "en", label: "English", nativeLabel: "English" },
  { code: "ja", label: "Japanese", nativeLabel: "日本語" },
];

export const DICTIONARY = {
  // ── App shell / nav ──────────────────────────────────────────────────
  "app.brand": { en: "JEPX-Storage", ja: "JEPXストレージ" },
  "nav.dashboard": { en: "Dashboard", ja: "ダッシュボード" },
  "nav.workbench": { en: "Workbench", ja: "ワークベンチ" },
  "nav.lab": { en: "Lab", ja: "ラボ" },
  "nav.signIn": { en: "Sign in", ja: "サインイン" },
  "nav.signOut": { en: "Sign out", ja: "サインアウト" },
  "nav.language": { en: "Language", ja: "言語" },

  // ── Dashboard page ───────────────────────────────────────────────────
  "dashboard.title": { en: "Japan power dashboard", ja: "日本電力ダッシュボード" },
  "dashboard.description": {
    en: "Half-hourly snapshots of demand, generation mix, and JEPX clearing across the 9 utility regions. Forecasts, stack model, and pipeline health under the tabs.",
    ja: "9電力エリアにおける需要、電源構成、JEPX約定価格の30分ごとのスナップショット。予測、スタックモデル、パイプラインの状態は各タブをご覧ください。",
  },
  "dashboard.updatedPrefix": { en: "Updated", ja: "更新" },
  "dashboard.refresh": { en: "Refresh", ja: "更新" },
  "dashboard.status.error": { en: "Error", ja: "エラー" },
  "dashboard.status.syncing": { en: "Syncing", ja: "同期中" },
  "dashboard.status.noData": { en: "No data", ja: "データなし" },
  "dashboard.status.live": { en: "Live", ja: "ライブ" },
  "dashboard.metric.systemDemand": { en: "System demand", ja: "系統需要" },
  "dashboard.metric.systemGen": { en: "System generation", ja: "系統発電量" },
  "dashboard.metric.systemVre": { en: "System VRE share", ja: "系統VRE比率" },
  "dashboard.metric.tokyoJepx": { en: "Tokyo JEPX", ja: "東京JEPX" },
  "dashboard.fetchFailed": {
    en: "Regional balance fetch failed:",
    ja: "エリア需給の取得に失敗しました：",
  },

  // ── Dashboard tabs ───────────────────────────────────────────────────
  "tab.map": { en: "Map", ja: "マップ" },
  "tab.strategy": { en: "Strategy", ja: "戦略" },
  "tab.forecast": { en: "Forecast", ja: "予測" },
  "tab.stack": { en: "Stack", ja: "スタック" },
  "tab.regime": { en: "Regime", ja: "レジーム" },
  "tab.health": { en: "Health", ja: "ヘルス" },

  // ── Map ──────────────────────────────────────────────────────────────
  "map.title": { en: "Regional snapshot", ja: "エリア別スナップショット" },
  "map.regions": { en: "9 JEPX utility regions", ja: "JEPX 9電力エリア" },
  "map.slotPrefix": { en: "Slot", ja: "スロット" },
  "map.metric.vreShare": { en: "VRE share", ja: "VRE比率" },
  "map.metric.vreShare.help": {
    en: "Share of demand met by solar, wind and hydro",
    ja: "太陽光・風力・水力で賄われる需要の割合",
  },
  "map.metric.balance": { en: "Balance", ja: "需給バランス" },
  "map.metric.balance.help": {
    en: "(Generation − Demand) / Demand",
    ja: "（発電量 − 需要）÷ 需要",
  },
  "map.metric.price": { en: "JEPX price", ja: "JEPX価格" },
  "map.metric.price.help": { en: "Day-ahead clearing, ¥/kWh", ja: "前日約定価格、¥/kWh" },
  "map.legend": { en: "Legend", ja: "凡例" },
  "map.legend.deficit": { en: "Deficit", ja: "不足" },
  "map.legend.balanced": { en: "Balanced", ja: "均衡" },
  "map.legend.surplus": { en: "Surplus", ja: "余剰" },
  "map.okinawa": { en: "Okinawa", ja: "沖縄" },
  "map.okinawa.partOfKy": { en: "part of KY", ja: "九州 (KY) の一部" },

  // ── Region names ─────────────────────────────────────────────────────
  "region.HK": { en: "Hokkaido", ja: "北海道" },
  "region.TH": { en: "Tohoku", ja: "東北" },
  "region.TK": { en: "Tokyo", ja: "東京" },
  "region.CB": { en: "Chubu", ja: "中部" },
  "region.HR": { en: "Hokuriku", ja: "北陸" },
  "region.KS": { en: "Kansai", ja: "関西" },
  "region.CG": { en: "Chugoku", ja: "中国" },
  "region.SK": { en: "Shikoku", ja: "四国" },
  "region.KY": { en: "Kyushu", ja: "九州" },

  // ── Region detail panel ──────────────────────────────────────────────
  "regionDetail.areaPrefix": { en: "Area", ja: "エリア" },
  "regionDetail.slotPrefix": { en: "slot", ja: "スロット" },
  "regionDetail.close": { en: "Close", ja: "閉じる" },
  "regionDetail.demand": { en: "Demand", ja: "需要" },
  "regionDetail.generation": { en: "Generation", ja: "発電量" },
  "regionDetail.balance": { en: "Balance", ja: "バランス" },
  "regionDetail.jepxDayAhead": { en: "JEPX day-ahead", ja: "JEPX前日" },
  "regionDetail.noBreakdown": {
    en: "No generation breakdown for this slot.",
    ja: "このスロットの電源構成データはありません。",
  },
  "regionDetail.fuel": { en: "Fuel", ja: "燃料" },
  "regionDetail.share": { en: "Share", ja: "シェア" },
  "regionDetail.seeStack": { en: "See stack curve →", ja: "スタック曲線を見る →" },

  // ── Strategy tab (Basket of Spreads) ─────────────────────────────────
  "strategy.title": { en: "Basket of Spreads", ja: "スプレッドバスケット" },
  "strategy.description": {
    en: "Decomposes storage value into a portfolio of calendar spread options on the slot forwards (one CSO per charge → discharge pair). Adapted from Baker/O'Brien/Ogden/Strickland, \"Gas storage valuation strategies\", Risk.net Nov 2017. Built greedy in spread value under power + inventory constraints; extrinsic value layered via Bachelier at-the-money approximation.",
    ja: "蓄電池の価値をスロットフォワードに対するカレンダースプレッドオプションのポートフォリオに分解します（充電→放電ペアごとに1つのCSO）。Baker・O'Brien・Ogden・Stricklandの「ガス貯蔵評価戦略」（Risk.net、2017年11月）を応用。出力および在庫制約のもとでスプレッド価値を貪欲法で構築し、エクストリンシック価値はバシュリエATM近似で重ねます。",
  },
  "strategy.forwardSource": { en: "Forward curve source", ja: "フォワードカーブの出典" },
  "strategy.source.forecast": { en: "VLSTM forecast", ja: "VLSTM予測" },
  "strategy.source.realised": { en: "Realised (28d)", ja: "実績 (28日)" },
  "strategy.horizon": { en: "Horizon", ja: "予測期間" },
  "strategy.horizon.1day": { en: "1 day (48 slots)", ja: "1日 (48スロット)" },
  "strategy.horizon.2days": { en: "2 days", ja: "2日" },
  "strategy.horizon.3_5days": { en: "3.5 days", ja: "3.5日" },
  "strategy.horizon.7days": { en: "7 days", ja: "7日" },
  "strategy.computing": { en: "Computing…", ja: "計算中…" },
  "strategy.recompute": { en: "Recompute", ja: "再計算" },
  "strategy.metric.bosTotalValue": { en: "BoS total value", ja: "BoS合計価値" },
  "strategy.metric.bosTotalValue.hint": { en: "across {n} CSOs", ja: "{n}件のCSO" },
  "strategy.metric.intrinsic": { en: "Intrinsic", ja: "イントリンシック" },
  "strategy.metric.extrinsic": { en: "Extrinsic", ja: "エクストリンシック" },
  "strategy.metric.perKwh": { en: "Per kWh of capacity", ja: "kWhあたり" },
  "strategy.schedule.title": { en: "Today's schedule", ja: "本日のスケジュール" },
  "strategy.schedule.description": {
    en: "Action implied by the optimal basket at each half-hour slot.",
    ja: "最適なバスケットが各30分スロットで指示するアクション。",
  },
  "strategy.action.charge": { en: "Charge", ja: "充電" },
  "strategy.action.discharge": { en: "Discharge", ja: "放電" },
  "strategy.action.idle": { en: "Idle", ja: "待機" },
  "strategy.window": { en: "window", ja: "ウィンドウ" },
  "strategy.windows": { en: "windows", ja: "ウィンドウ" },
  "strategy.physical.title": { en: "Physical profile", ja: "物理プロファイル" },
  "strategy.physical.description": {
    en: "Half-hourly charge (green, up) / discharge (red, down) and running inventory (blue line) over the horizon.",
    ja: "予測期間中の30分ごとの充電（緑、上向き）/ 放電（赤、下向き）と現在在庫（青線）。",
  },
  "strategy.chartLabel.charge": { en: "Charge", ja: "充電" },
  "strategy.chartLabel.discharge": { en: "Discharge", ja: "放電" },
  "strategy.chartLabel.inventory": { en: "Inventory", ja: "在庫" },
  "strategy.pnl.title": { en: "Expected P&L over time", ja: "期待損益の推移" },
  "strategy.pnl.description": {
    en: "Cumulative cashflow while executing the basket against the forward curve. Down-slopes are charge slots (paying for energy); up-slopes are discharge slots (revenue).",
    ja: "フォワードカーブに対してバスケットを執行する際の累積キャッシュフロー。下向きは充電スロット（電力購入支出）、上向きは放電スロット（売電収益）です。",
  },
  "strategy.pnl.chargeSpend": { en: "Charge spend", ja: "充電支出" },
  "strategy.pnl.dischargeRevenue": { en: "Discharge revenue", ja: "放電収益" },
  "strategy.pnl.finalPnl": { en: "Final P&L", ja: "最終損益" },
  "strategy.pnl.cumulative": { en: "Cumulative P&L", ja: "累積損益" },
  "strategy.pnl.cumDischarge": { en: "Cum. discharge revenue", ja: "累積放電収益" },
  "strategy.pnl.cumCharge": { en: "Cum. charge spend (negative)", ja: "累積充電支出（マイナス）" },
  "strategy.pnl.intrinsicTarget": { en: "Intrinsic target", ja: "イントリンシック目標" },
  "strategy.pnl.bosTotal": { en: "BoS total", ja: "BoS合計" },
  "strategy.basket.title": { en: "Basket composition", ja: "バスケット構成" },
  "strategy.basket.description": {
    en: "Optimal CSO portfolio sorted by total value (intrinsic + extrinsic). Each row pairs a charge slot with a discharge slot at the volume that maximises value without violating power-rate or capacity constraints.",
    ja: "総価値（イントリンシック＋エクストリンシック）順に並べた最適CSOポートフォリオ。各行は出力レートと容量制約を満たしつつ価値を最大化する数量で、充電スロットと放電スロットをペアにします。",
  },
  "strategy.basket.empty": {
    en: "No profitable spreads in this horizon.",
    ja: "この予測期間には収益性のあるスプレッドがありません。",
  },
  "strategy.basket.chargeSlot": { en: "Charge slot", ja: "充電スロット" },
  "strategy.basket.dischargeSlot": { en: "Discharge slot", ja: "放電スロット" },
  "strategy.basket.volume": { en: "Volume (MWh)", ja: "数量 (MWh)" },
  "strategy.basket.spread": { en: "Spread (¥/kWh)", ja: "スプレッド (¥/kWh)" },
  "strategy.basket.spreadVol": { en: "σ_spread (¥/kWh)", ja: "σ_スプレッド (¥/kWh)" },
  "strategy.basket.totalCol": { en: "Total", ja: "合計" },
  "strategy.peakInventory": { en: "Peak inventory", ja: "ピーク在庫" },
  "strategy.fullCycles": { en: "full cycle", ja: "フルサイクル" },
  "strategy.fullCyclesPlural": { en: "full cycles", ja: "フルサイクル" },
  "strategy.chargeAvg": { en: "at average", ja: "平均" },
  "strategy.in": { en: "in", ja: " " },

  // ── Forecast panel ───────────────────────────────────────────────────
  "forecast.title": { en: "Section B — Forecast fan chart", ja: "セクションB — 予測ファンチャート" },
  "forecast.description.prefix": {
    en: "Latest VLSTM forecast: 1000 plausible price paths × 48 half-hour slots. Mean line plus 5/25/75/95 percentile ribbons. Toggle the stack-modelled fundamental price overlay or shade the chart by",
    ja: "最新のVLSTM予測：1000本の価格パス × 48個の30分スロット。平均線と5/25/75/95パーセンタイル帯。スタックモデルのファンダメンタル価格を重ねたり、次の項目でチャートを色分けできます：",
  },
  "forecast.area": { en: "Area", ja: "エリア" },
  "forecast.overlayStack": { en: "Overlay stack price", ja: "スタック価格を重ねる" },
  "forecast.showStack": { en: "Show stack-modelled price", ja: "スタックモデル価格を表示" },
  "forecast.colorByRegime": { en: "Colour by regime", ja: "レジームで色分け" },
  "forecast.shadeByRegime": { en: "Shade by most-likely regime", ja: "最尤レジームで色付け" },
  "forecast.errorPrefix": { en: "Error:", ja: "エラー：" },
  "forecast.originPrefix": { en: "Origin:", ja: "起点：" },
  "forecast.pathsSuffix": { en: "paths · run id", ja: "パス · 実行ID" },
  "forecast.bandLabel90": { en: "5–95% band", ja: "5–95%帯" },
  "forecast.bandLabel50": { en: "25–75% band", ja: "25–75%帯" },
  "forecast.meanLabel": { en: "Mean forecast", ja: "平均予測" },
  "forecast.stackLabel": { en: "Stack model", ja: "スタックモデル" },
  "forecast.empty.prefix": {
    en: "No forecast paths yet. Run",
    ja: "予測パスがまだありません。次のコマンドを実行してください：",
  },
  "forecast.empty.middle": { en: "or wait for the twice-daily", ja: "または1日2回の" },
  "forecast.empty.suffix": { en: "cron (07:00 / 22:00 JST).", ja: "クロン (JST 07:00 / 22:00) をお待ちください。" },
  "forecast.yAxisLabel": { en: "Price (¥/kWh)", ja: "価格 (¥/kWh)" },

  // ── Cron health strip ────────────────────────────────────────────────
  "cron.title": { en: "Cron health (7 days)", ja: "クロン状態 (7日間)" },
  "cron.description": {
    en: "Per-kind status for each of the last 7 days. Click a red square to see the error.",
    ja: "過去7日間の種別ごとの状態。赤いマスをクリックするとエラー内容を表示します。",
  },
  "cron.kind": { en: "Kind", ja: "種別" },
  "cron.failedOn": { en: "Failed on", ja: "失敗日：" },
  "cron.noError": { en: "(no error message)", ja: "（エラーメッセージなし）" },
  "cron.close": { en: "Close", ja: "閉じる" },

  // ── Compute runs table ───────────────────────────────────────────────
  "compute.ingest": { en: "Ingest", ja: "データ取込" },
  "compute.ingest.description": {
    en: "Daily ingest pipeline: market, demand, generation mix, weather, FX, fuel, holidays.",
    ja: "日次取込パイプライン：市場、需要、電源構成、気象、為替、燃料、祝日。",
  },
  "compute.models": { en: "Models", ja: "モデル" },
  "compute.models.description": {
    en: "Regime calibration, VLSTM training, twice-daily forecast inference.",
    ja: "レジームキャリブレーション、VLSTM学習、1日2回の予測推論。",
  },
  "compute.compute": { en: "Compute", ja: "計算" },
  "compute.compute.description": {
    en: "Stack build, on-demand LSM valuations, strategy backtests.",
    ja: "スタック構築、オンデマンドLSM評価、戦略バックテスト。",
  },

  // ── Workbench page ───────────────────────────────────────────────────
  "workbench.title": { en: "Workbench", ja: "ワークベンチ" },
  "workbench.description": {
    en: "Daily Boogert & de Jong Least-Squares Monte Carlo valuation of a 100 MWh / 50 MW Tokyo BESS against the latest VLSTM forecast paths. Refreshes automatically every morning at 06:30 JST after the day's ingest + stack build complete.",
    ja: "100 MWh / 50 MW の東京BESSを最新のVLSTM予測パスに対してBoogert & de Jong最小二乗モンテカルロで日次評価します。毎朝06:30 JSTにその日の取込とスタック構築完了後に自動更新されます。",
  },
  "workbench.empty": {
    en: "The demo valuation hasn't run yet. The first cron firing after this deploy will populate it.",
    ja: "デモ評価はまだ実行されていません。このデプロイ後の最初のクロンで作成されます。",
  },

  // ── Lab page ─────────────────────────────────────────────────────────
  "lab.title": { en: "Strategy lab", ja: "戦略ラボ" },
  "lab.description.prefix": {
    en: "Four dispatch strategies (naive spread, intrinsic, rolling intrinsic, LSM) replayed daily on realised JEPX history for the demo 100 MWh / 50 MW Tokyo BESS. Compare cumulative P&L, Sharpe, and max drawdown after slippage.",
    ja: "4つのディスパッチ戦略（ナイーブスプレッド、イントリンシック、ローリングイントリンシック、LSM）を、デモの100 MWh / 50 MW 東京BESSに対し実績JEPX履歴で日次再生します。スリッページ後の累積損益、シャープ、最大ドローダウンを比較します。",
  },
  "lab.window": { en: "Window:", ja: "期間：" },
  "lab.emptyWindow": { en: "(no demo run yet)", ja: "（デモ実行なし）" },
  "lab.empty": {
    en: "The demo backtests haven't run yet. The first cron firing after this deploy will populate them.",
    ja: "デモバックテストはまだ実行されていません。このデプロイ後の最初のクロンで作成されます。",
  },
} as const;

export type TranslationKey = keyof typeof DICTIONARY;
