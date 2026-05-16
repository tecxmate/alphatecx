"use client";

import { TickerChip } from "@/components/tools/ticker-chip";
import { useEffect, useState } from "react";

type Row = {
  ticker_id?: string;
  name?: string;
  company_name?: string;
  reason?: string;
};

export function WatchlistPanel() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/watchlist")
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        setRows(d.watchlist ?? []);
        if (d.error) setError(String(d.error));
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (rows === null) {
    return (
      <div className="px-3 py-2 text-xs text-muted-foreground">
        Loading watchlist…
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-muted-foreground">
        {error ? `Watchlist unavailable (${error.slice(0, 80)})` : "Watchlist is empty."}
      </div>
    );
  }
  return (
    <div className="space-y-1 px-2 pb-2">
      {rows.map((r) =>
        r.ticker_id ? (
          <div
            key={r.ticker_id}
            className="rounded px-2 py-1 text-xs transition-colors hover:bg-sidebar-accent"
          >
            <div className="flex items-baseline justify-between gap-2">
              <TickerChip
                ticker={r.ticker_id}
                className="text-left font-mono text-sm font-semibold hover:underline"
              />
              <span className="truncate text-muted-foreground">
                {r.name ?? r.company_name}
              </span>
            </div>
            {r.reason && (
              <div className="truncate text-muted-foreground">{r.reason}</div>
            )}
          </div>
        ) : null,
      )}
    </div>
  );
}
