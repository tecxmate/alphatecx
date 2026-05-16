"use client";

import {
  AssistantCloud,
  AssistantRuntimeProvider,
  McpAppRenderer,
  McpAppsRemoteHost,
  Tools,
  useAui,
} from "@assistant-ui/react";
import { useMemo } from "react";
import {
  useChatRuntime,
  AssistantChatTransport,
} from "@assistant-ui/react-ai-sdk";
import { lastAssistantMessageIsCompleteWithToolCalls } from "ai";
import { AutoTitle } from "@/components/assistant-ui/auto-title";
import { HeaderTitle } from "@/components/assistant-ui/header-title";
import { Thread } from "@/components/assistant-ui/thread";
import { ChipFlowChartUI } from "@/components/tools/chip-flow-chart";
import { IndicatorsCardsUI } from "@/components/tools/indicators-cards";
import { NewsForTickerUI, NewsRecentUI } from "@/components/tools/news-feed";
import { RegimeBadgeUI } from "@/components/tools/regime-badge";
import { ScreenerTableUI } from "@/components/tools/screener-table";
import { SupplyChainListUI } from "@/components/tools/supply-chain-list";
import { TickerMomentumUI } from "@/components/tools/ticker-momentum";
import { WatchlistTableUI } from "@/components/tools/watchlist-table";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { ThreadListSidebar } from "@/components/assistant-ui/threadlist-sidebar";
import { Separator } from "@/components/ui/separator";

export const Assistant = () => {
  // Anonymous Cloud persists thread list, messages, and AI-generated titles
  // per browser session. Falls back to in-memory only when the env var is
  // unset, so the app still runs without a Cloud account.
  const cloud = useMemo(() => {
    const baseUrl = process.env.NEXT_PUBLIC_ASSISTANT_BASE_URL;
    if (!baseUrl) return undefined;
    return new AssistantCloud({ baseUrl, anonymous: true });
  }, []);

  const runtime = useChatRuntime({
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithToolCalls,
    transport: new AssistantChatTransport({
      api: "/api/chat",
    }),
    cloud,
  });

  const aui = useAui({
    tools: Tools({
      mcpApp: McpAppRenderer({
        host: McpAppsRemoteHost({ url: "/api/mcp-apps" }),
        hostInfo: { name: "taistock-terminal", version: "0.1.0" },
      }),
    }),
  });

  return (
    <AssistantRuntimeProvider aui={aui} runtime={runtime}>
      <ChipFlowChartUI />
      <ScreenerTableUI />
      <SupplyChainListUI />
      <IndicatorsCardsUI />
      <TickerMomentumUI />
      <NewsRecentUI />
      <NewsForTickerUI />
      <WatchlistTableUI />
      <RegimeBadgeUI />
      <AutoTitle />
      <SidebarProvider>
        <div className="flex h-dvh w-full pr-0.5">
          <ThreadListSidebar />
          <SidebarInset>
            <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
              <SidebarTrigger />
              <Separator orientation="vertical" className="mr-2 h-4" />
              <HeaderTitle />
            </header>
            <div className="flex-1 overflow-hidden">
              <Thread />
            </div>
          </SidebarInset>
        </div>
      </SidebarProvider>
    </AssistantRuntimeProvider>
  );
};
