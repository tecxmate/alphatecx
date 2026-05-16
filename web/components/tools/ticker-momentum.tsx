"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import { ProvenanceFooter, type Provenance } from "./provenance";
import { TickerChip } from "./ticker-chip";

type Ticker = {
  ticker_id?: string;
  name?: string;
  pillar?: string;
  node?: string;
  foreign_1d?: number;
  foreign_3d?: number;
  foreign_5d?: number;
  foreign_10d?: number;
  foreign_20d?: number;
  buy_streak?: number;
};

type Args = {
  pillar?: string;
  node?: string;
  ticker_id?: string;
  window?: string;
  top_n?: number;
  min_streak?: number;
};
type Result = Provenance & {
  tickers?: Ticker[];
  window?: string;
  count?: number;
};

function flowTint(n?: number) {
  if (n == null) return "";
  if (n > 0) return "text-emerald-600 dark:text-emerald-400";
  if (n < 0) return "text-red-600 dark:text-red-400";
  return "text-muted-foreground";
}

export const TickerMomentumUI = makeAssistantToolUI<Args, Result>({
  toolName: "sc_ticker_momentum",
  render: ({ args, result, status }) => {
    if (status.type !== "complete" || !result) {
      return (
        <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          Computing ticker momentum…
        </div>
      );
    }
    const tickers = result.tickers ?? [];
    const w = (result.window ?? args.window ?? "5d") as
      | "1d"
      | "3d"
      | "5d"
      | "10d"
      | "20d";
    const flowKey = `foreign_${w}` as keyof Ticker;
    if (tickers.length === 0) {
      return (
        <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          No tickers matched.
          <ProvenanceFooter data={result} />
        </div>
      );
    }
    return (
      <div className="rounded-md border bg-card p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium">
            Ticker momentum — {tickers.length} matches
          </span>
          <span className="text-xs text-muted-foreground">window {w}</span>
        </div>
        <div className="space-y-1.5">
          {tickers.map((t) => {
            const flow = t[flowKey] as number | undefined;
            return (
              <div
                key={t.ticker_id}
                className="flex items-center gap-3 rounded border bg-background px-2 py-1.5 text-xs"
              >
                {t.ticker_id ? (
                  <TickerChip ticker={t.ticker_id} className="w-14 text-left font-mono font-semibold hover:underline" />
                ) : (
                  <span className="w-14" />
                )}
                <span className="flex-1 truncate text-muted-foreground">
                  {t.name}
                </span>
                {t.node && (
                  <span className="rounded bg-muted px-1.5 py-0.5">
                    {t.node}
                  </span>
                )}
                {t.buy_streak != null && t.buy_streak > 0 && (
                  <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                    {t.buy_streak}d streak
                  </span>
                )}
                <span className={`w-24 text-right font-mono ${flowTint(flow)}`}>
                  {flow != null ? flow.toLocaleString() : "—"}
                </span>
              </div>
            );
          })}
        </div>
        <ProvenanceFooter data={result} />
      </div>
    );
  },
});
