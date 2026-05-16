"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import { useMemo } from "react";
import { ProvenanceFooter, type Provenance } from "./provenance";
import { TickerChip } from "./ticker-chip";

type Company = {
  ticker_id?: string;
  name?: string;
  pillar?: string;
  node?: string;
  us_partners?: string[] | string;
};

type Args = { pillar?: string; node?: string; search?: string };
type Result = Provenance & { companies?: Company[]; count?: number };

export const SupplyChainListUI = makeAssistantToolUI<Args, Result>({
  toolName: "sc_supply_chain_map",
  render: ({ result, status }) => {
    if (status.type !== "complete" || !result) {
      return (
        <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          Looking up supply chain…
        </div>
      );
    }
    const companies = result.companies ?? [];
    return <SupplyChainList companies={companies} provenance={result} />;
  },
});

function SupplyChainList({
  companies,
  provenance,
}: {
  companies: Company[];
  provenance: Provenance;
}) {
  const grouped = useMemo(() => {
    const m = new Map<string, Company[]>();
    for (const c of companies) {
      const key = `${c.pillar ?? "—"} / ${c.node ?? "—"}`;
      if (!m.has(key)) m.set(key, []);
      m.get(key)!.push(c);
    }
    return [...m.entries()];
  }, [companies]);

  if (companies.length === 0) {
    return (
      <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
        No supply chain matches.
        <ProvenanceFooter data={provenance} />
      </div>
    );
  }

  return (
    <div className="rounded-md border bg-card p-3">
      <div className="mb-2 text-sm font-medium">
        Supply chain — {companies.length} companies
      </div>
      <div className="space-y-3">
        {grouped.map(([group, items]) => (
          <div key={group}>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {group}
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {items.map((c) => {
                const partners = Array.isArray(c.us_partners)
                  ? c.us_partners.join(", ")
                  : c.us_partners ?? "";
                return (
                  <span
                    key={`${c.ticker_id}-${c.name}`}
                    className="rounded border bg-background px-2 py-0.5 text-xs"
                    title={partners}
                  >
                    {c.ticker_id ? (
                      <TickerChip ticker={c.ticker_id} />
                    ) : (
                      <span className="font-mono">—</span>
                    )}{" "}
                    <span className="text-muted-foreground">{c.name}</span>
                  </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <ProvenanceFooter data={provenance} />
    </div>
  );
}
