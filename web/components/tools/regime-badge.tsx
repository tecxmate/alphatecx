"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import { ProvenanceFooter, type Provenance } from "./provenance";

type Args = { window?: number; days?: number };
type Result = Provenance & {
  regime_label?: string;
  vol_regime?: string;
  corr_regime?: string;
  vol_annualised?: number;
  avg_correlation?: number;
  vol_trend?: string;
  corr_trend?: string;
  window?: number;
};

function regimeColor(label?: string): string {
  if (!label) return "bg-muted text-foreground";
  if (label.includes("low_vol_dispersed"))
    return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300";
  if (label.includes("high_vol_crowded"))
    return "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300";
  if (label.includes("high_vol"))
    return "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300";
  if (label.includes("crowded"))
    return "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300";
  return "bg-muted text-foreground";
}

function trendArrow(t?: string): string {
  if (t === "rising") return "↑";
  if (t === "falling") return "↓";
  return "→";
}

export const RegimeBadgeUI = makeAssistantToolUI<Args, Result>({
  toolName: "q_regime",
  render: ({ result, status }) => {
    if (status.type !== "complete" || !result) {
      return (
        <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          Computing regime…
        </div>
      );
    }
    return (
      <div className="rounded-md border bg-card p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium">Market regime</span>
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${regimeColor(result.regime_label)}`}
          >
            {result.regime_label ?? "unknown"}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded border bg-background p-2">
            <div className="text-xs text-muted-foreground">
              Volatility ({result.vol_regime ?? "—"}){" "}
              {trendArrow(result.vol_trend)}
            </div>
            <div className="font-mono text-sm font-semibold">
              {result.vol_annualised != null
                ? `${(result.vol_annualised * 100).toFixed(1)}%`
                : "—"}
            </div>
          </div>
          <div className="rounded border bg-background p-2">
            <div className="text-xs text-muted-foreground">
              Correlation ({result.corr_regime ?? "—"}){" "}
              {trendArrow(result.corr_trend)}
            </div>
            <div className="font-mono text-sm font-semibold">
              {result.avg_correlation != null
                ? result.avg_correlation.toFixed(2)
                : "—"}
            </div>
          </div>
        </div>
        <ProvenanceFooter data={result} />
      </div>
    );
  },
});
