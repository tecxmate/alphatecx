"use client";

import { useTitleStore } from "@/lib/title-store";
import { useAui, useAuiState } from "@assistant-ui/react";
import { useEffect, useRef } from "react";

// Fires once per thread: after the first assistant turn completes, grab the
// first user message and ask /api/title for a short title. Stores it in
// useTitleStore keyed by thread id.
export function AutoTitle() {
  const aui = useAui();
  const messageCount = useAuiState((s) => s.thread.messages.length);
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const lastTriedRef = useRef<string | null>(null);
  const setTitle = useTitleStore((s) => s.setTitle);
  const markPending = useTitleStore((s) => s.markPending);
  const pending = useTitleStore((s) => s.pending);
  const titles = useTitleStore((s) => s.titles);

  useEffect(() => {
    if (isRunning || messageCount < 2) return;
    const messages = aui.thread().getState().messages;
    // Need at least one user + one assistant turn to title.
    const firstUser = messages.find((m) => m.role === "user");
    if (!firstUser) return;
    const threadId = aui.threadListItem?.().getState?.()?.id;
    if (!threadId) return;
    if (titles[threadId]) return;
    if (pending[threadId]) return;
    if (lastTriedRef.current === threadId) return;
    lastTriedRef.current = threadId;
    const text = firstUser.content
      .filter((p: any) => p.type === "text")
      .map((p: any) => p.text)
      .join(" ")
      .trim();
    if (!text) return;
    markPending(threadId);
    fetch("/api/title", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.title) setTitle(threadId, d.title);
      })
      .catch(() => {
        // swallow; lastTriedRef prevents retry storm
      });
  }, [aui, messageCount, isRunning, titles, pending, markPending, setTitle]);

  return null;
}
