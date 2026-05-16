"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import { ProvenanceFooter, type Provenance } from "./provenance";

type Article = {
  title?: string;
  summary?: string;
  url?: string;
  source?: string;
  lang?: string;
  published_at?: string;
};

type Args = {
  days?: number;
  source?: string;
  lang?: string;
  limit?: number;
  ticker_id?: string;
};
type Result = Provenance & {
  articles?: Article[];
  count?: number;
  days_window?: number;
  ticker_id?: string;
};

function NewsFeed({
  args,
  result,
  status,
}: {
  args: Args;
  result?: Result;
  status: { type: string };
}) {
  if (status.type !== "complete" || !result) {
    return (
      <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
        Loading news…
      </div>
    );
  }
  const articles = result.articles ?? [];
  if (articles.length === 0) {
    return (
      <div className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
        No articles in the last {result.days_window ?? args.days ?? 1}d.
        <ProvenanceFooter data={result} />
      </div>
    );
  }
  return (
    <div className="rounded-md border bg-card p-3">
      <div className="mb-2 text-sm font-medium">
        {result.ticker_id ? `${result.ticker_id} news` : "Recent news"} —{" "}
        {articles.length} articles
      </div>
      <div className="max-h-96 space-y-2 overflow-auto pr-1">
        {articles.map((a, i) => (
          <a
            key={`${a.url ?? i}`}
            href={a.url ?? "#"}
            target="_blank"
            rel="noopener noreferrer"
            className="block rounded border bg-background p-2 transition-colors hover:bg-muted"
          >
            <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
              <span>{a.source ?? "—"}</span>
              <span>{a.published_at?.slice(0, 16).replace("T", " ")}</span>
            </div>
            <div className="text-sm font-medium leading-snug">{a.title}</div>
            {a.summary && (
              <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                {a.summary}
              </div>
            )}
          </a>
        ))}
      </div>
      <ProvenanceFooter data={result} />
    </div>
  );
}

export const NewsRecentUI = makeAssistantToolUI<Args, Result>({
  toolName: "n_recent",
  render: NewsFeed,
});

export const NewsForTickerUI = makeAssistantToolUI<Args, Result>({
  toolName: "n_for_ticker",
  render: NewsFeed,
});
