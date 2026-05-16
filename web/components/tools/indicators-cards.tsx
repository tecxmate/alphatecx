"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import { ProvenanceFooter, type Provenance } from "./provenance";

type Args = { ticker_id: string };
type Result = Provenance &
  Record<string, unknown> & {
    ticker_id?: string;
    rsi_14?: number;
    macd_line?: number;
    macd_signal?: number;
    macd_hist?: number;
    bb_pct_b?: number;
    atr_14?: number;
    sma_50?: number;
    sma_200?: number;
    rs_60?: number;
    close?: number;
  };

const FIELDS: { key: keyof Result; label: string; fmt?: (n: number) => string }[] = [
  { key: "close", label: "Close" },
  { key: "rsi_14", label: "RSI-14" },
  { key: "macd_hist", label: "MACD hist" },
  { key: "bb_pct_b", label: "BB %B", fmt: (n) => (n * 100).toFixed(1) + "%" },
  { key: "atr_14", label: "ATR-14" },
  { key: "sma_50", label: "SMA-50" },
  { key: "sma_200", label: "SMA-200" },
  { key: "rs_60", label: "RS vs 0050", fmt: (n) => (n * 100).toFixed(2) + "%" },
];

function rsiTint(v?: number): string {
  if (v == null) return "";
  if (v >= 70) return "text-red-600 dark:text-red-400";
  if (v <= 30) return "text-emerald-600 dark:text-emerald-400";
  return "";
}

export const IndicatorsCardsUI = makeAssistantToolUI<Args, Result>({
  toolName: "q_indicators",
  render: ({ args, result, status }) => {
    if (status.type !== "complete" || !result) {
      return (
        <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          Loading indicators for {args.ticker_id}…
        </div>
      );
    }
    return (
      <div className="rounded-md border bg-card p-3">
        <div className="mb-2 text-sm font-medium">
          {result.ticker_id ?? args.ticker_id} — technical snapshot
        </div>
        <div className="grid grid-cols-2 gap-2 @md:grid-cols-4">
          {FIELDS.map(({ key, label, fmt }) => {
            const raw = result[key];
            if (raw == null || typeof raw !== "number") return null;
            const text = fmt ? fmt(raw) : raw.toLocaleString();
            const tint = key === "rsi_14" ? rsiTint(raw) : "";
            return (
              <div key={String(key)} className="rounded border bg-background p-2">
                <div className="text-xs text-muted-foreground">{label}</div>
                <div className={`text-sm font-mono font-semibold ${tint}`}>
                  {text}
                </div>
              </div>
            );
          })}
        </div>
        <ProvenanceFooter data={result} />
      </div>
    );
  },
});
