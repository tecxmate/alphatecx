"use client";

import { useTitleStore } from "@/lib/title-store";
import { useAui, useAuiState } from "@assistant-ui/react";

// Prefers the Cloud-managed title from the runtime when available, falls
// back to the local title-store written by AutoTitle for non-Cloud setups.
export function HeaderTitle() {
  const aui = useAui();
  const messageCount = useAuiState((s) => s.thread.messages.length);
  const runtimeTitle = useAuiState(
    (s) => (s as any).threadListItem?.title as string | undefined,
  );
  const threadId = (aui as any).threadListItem?.().getState?.()?.id as
    | string
    | undefined;
  const localTitle = useTitleStore((s) =>
    threadId ? s.titles[threadId] : undefined,
  );
  const title = runtimeTitle || localTitle;
  if (title) {
    return <span className="truncate font-medium">{title}</span>;
  }
  if (messageCount === 0) {
    return <span className="text-muted-foreground">New chat</span>;
  }
  return <span className="text-muted-foreground">Untitled chat</span>;
}
