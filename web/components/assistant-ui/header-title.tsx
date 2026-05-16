"use client";

import { useTitleStore } from "@/lib/title-store";
import { useAui, useAuiState } from "@assistant-ui/react";

export function HeaderTitle() {
  const aui = useAui();
  const messageCount = useAuiState((s) => s.thread.messages.length);
  const threadId = (aui as any).threadListItem?.().getState?.()?.id as
    | string
    | undefined;
  const title = useTitleStore((s) =>
    threadId ? s.titles[threadId] : undefined,
  );
  if (title) {
    return <span className="truncate font-medium">{title}</span>;
  }
  if (messageCount === 0) {
    return <span className="text-muted-foreground">New chat</span>;
  }
  return <span className="text-muted-foreground">Untitled chat</span>;
}
