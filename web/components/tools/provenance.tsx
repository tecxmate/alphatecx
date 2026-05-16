import type { ReactNode } from "react";

export type Provenance = {
  _source?: string;
  _as_of?: string;
  _freshness?: string;
};

export function ProvenanceFooter({ data }: { data: Provenance }) {
  const parts: ReactNode[] = [];
  if (data._source) parts.push(<span key="s">source: {data._source}</span>);
  if (data._as_of) parts.push(<span key="a">as of {data._as_of}</span>);
  if (data._freshness) parts.push(<span key="f">{data._freshness}</span>);
  if (parts.length === 0) return null;
  return (
    <div className="mt-2 flex gap-2 text-xs text-muted-foreground">
      {parts.map((p, i) => (
        <span key={i} className="rounded bg-muted px-1.5 py-0.5">
          {p}
        </span>
      ))}
    </div>
  );
}
