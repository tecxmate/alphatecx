"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { ProvenanceFooter, type Provenance } from "./provenance";
import { TickerChip } from "./ticker-chip";

type Row = Record<string, unknown> & { ticker_id?: string };

type Args = {
  min_streak?: number;
  min_foreign_5d?: number;
  pillar?: string;
  top_n?: number;
};
type Result = Provenance & {
  results?: Row[];
  rows?: Row[];
  count?: number;
};

export const ScreenerTableUI = makeAssistantToolUI<Args, Result>({
  toolName: "sc_accumulation_screen",
  render: ({ result, status }) => {
    if (status.type !== "complete" || !result) {
      return (
        <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          Running screener…
        </div>
      );
    }
    const rows = result.results ?? result.rows ?? [];
    return <ScreenerTable rows={rows} provenance={result} />;
  },
});

function ScreenerTable({
  rows,
  provenance,
}: {
  rows: Row[];
  provenance: Provenance;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const columns = useMemo<ColumnDef<Row>[]>(() => {
    if (rows.length === 0) return [];
    return Object.keys(rows[0]).map((key) => ({
      accessorKey: key,
      header: key,
      cell: ({ getValue }) => {
        const v = getValue();
        if (key === "ticker_id" && typeof v === "string") {
          return <TickerChip ticker={v} />;
        }
        if (typeof v === "number") return v.toLocaleString();
        return String(v ?? "");
      },
    }));
  }, [rows]);
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (rows.length === 0) {
    return (
      <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
        Screener returned no matches.
        <ProvenanceFooter data={provenance} />
      </div>
    );
  }

  return (
    <div className="rounded-md border bg-card p-3">
      <div className="mb-2 text-sm font-medium">
        Accumulation screen — {rows.length} matches
      </div>
      <div className="max-h-96 overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-card">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b">
                {hg.headers.map((h) => (
                  <th
                    key={h.id}
                    className="cursor-pointer px-2 py-1 text-left font-medium"
                    onClick={h.column.getToggleSortingHandler()}
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {{ asc: " ↑", desc: " ↓" }[
                      h.column.getIsSorted() as string
                    ] ?? ""}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((r) => (
              <tr key={r.id} className="border-b last:border-0">
                {r.getVisibleCells().map((c) => (
                  <td key={c.id} className="px-2 py-1">
                    {flexRender(c.column.columnDef.cell, c.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ProvenanceFooter data={provenance} />
    </div>
  );
}
