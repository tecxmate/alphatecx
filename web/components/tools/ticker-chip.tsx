"use client";

import { ThreadPrimitive } from "@assistant-ui/react";
import type { ReactNode } from "react";

// Clickable ticker that sends a follow-up prompt into the chat.
// Used inside generative-UI tool components to let the user drill into a
// specific ticker without retyping. Defaults to a chip-flow query because
// that's the most common follow-up after seeing a ticker in a list.
export function TickerChip({
  ticker,
  prompt,
  children,
  className,
}: {
  ticker: string;
  prompt?: string;
  children?: ReactNode;
  className?: string;
}) {
  const send =
    prompt ??
    `Show the institutional chip flow for ${ticker} over the last 30 trading days, and call out anything unusual.`;
  return (
    <ThreadPrimitive.Suggestion prompt={send} send asChild>
      <button
        type="button"
        className={
          className ??
          "cursor-pointer font-mono font-semibold underline-offset-2 hover:underline"
        }
        title={`Ask about ${ticker}`}
      >
        {children ?? ticker}
      </button>
    </ThreadPrimitive.Suggestion>
  );
}
