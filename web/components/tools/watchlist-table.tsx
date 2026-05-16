"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import { ProvenanceFooter, type Provenance } from "./provenance";
import { TickerChip } from "./ticker-chip";

type Row = {
  ticker_id?: string;
  name?: string;
  company_name?: string;
  reason?: string;
  status?: string;
  added_at?: string;
};

type Args = { status?: string };
type Result = Provenance & {
  watchlist?: Row[];
  count?: number;
  status?: string;
};

export const WatchlistTableUI = makeAssistantToolUI<Args, Result>({
  toolName: "w_watchlist",
  render: ({ result, status }) => {
    if (status.type !== "complete" || !result) {
      return (
        <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          Loading watchlist…
        </div>
      );
    }
    const rows = result.watchlist ?? [];
    if (rows.length === 0) {
      return (
        <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          Watchlist is empty ({result.status ?? "active"}).
          <ProvenanceFooter data={result} />
        </div>
      );
    }
    return (
      <div className="rounded-md border bg-card p-3">
        <div className="mb-2 text-sm font-medium">
          Watchlist — {rows.length} {result.status ?? "active"}
        </div>
        <div className="space-y-1.5">
          {rows.map((r) => (
            <div
              key={r.ticker_id}
              className="flex items-start gap-3 rounded border bg-background px-2 py-1.5 text-xs"
            >
              {r.ticker_id ? (
                <TickerChip
                  ticker={r.ticker_id}
                  className="w-14 text-left font-mono font-semibold hover:underline"
                />
              ) : (
                <span className="w-14" />
              )}
              <div className="flex-1">
                <div className="text-sm">{r.name ?? r.company_name ?? r.ticker_id}</div>
                {r.reason && (
                  <div className="text-muted-foreground">{r.reason}</div>
                )}
              </div>
              {r.added_at && (
                <span className="text-muted-foreground">
                  {r.added_at.slice(0, 10)}
                </span>
              )}
            </div>
          ))}
        </div>
        <ProvenanceFooter data={result} />
      </div>
    );
  },
});
