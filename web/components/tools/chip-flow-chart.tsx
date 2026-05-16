"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ProvenanceFooter, type Provenance } from "./provenance";

type FlowRow = {
  trade_date: string;
  foreign_net?: number;
  trust_net?: number;
  dealer_net?: number;
};

type Args = { ticker_id: string; days?: number };
type Result = Provenance & {
  ticker_id: string;
  count: number;
  history: FlowRow[];
};

// raw_flow_history: time series of foreign/trust/dealer net flows for a ticker.
export const ChipFlowChartUI = makeAssistantToolUI<Args, Result>({
  toolName: "raw_flow_history",
  render: ({ args, result, status }) => {
    if (status.type !== "complete" || !result) {
      return (
        <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          Loading chip flow for {args.ticker_id}…
        </div>
      );
    }
    const data = (result.history ?? []).slice().reverse();
    return (
      <div className="rounded-md border bg-card p-3">
        <div className="mb-2 text-sm font-medium">
          {result.ticker_id} — institutional net flow ({result.count} sessions)
        </div>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="trade_date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="foreign_net" name="Foreign" fill="#2563eb" />
              <Bar dataKey="trust_net" name="Trust" fill="#16a34a" />
              <Bar dataKey="dealer_net" name="Dealer" fill="#dc2626" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <ProvenanceFooter data={result} />
      </div>
    );
  },
});
