import type * as React from "react";
import { TrendingUp } from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { SettingsDialog } from "@/components/assistant-ui/settings-dialog";
import { ThreadList } from "@/components/assistant-ui/thread-list";
import { WatchlistPanel } from "@/components/assistant-ui/watchlist-panel";

export function ThreadListSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  return (
    <Sidebar {...props}>
      <SidebarHeader className="aui-sidebar-header mb-2 border-b">
        <div className="aui-sidebar-header-content flex items-center justify-between">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" asChild>
                <a href="/" rel="noopener noreferrer">
                  <div className="aui-sidebar-header-icon-wrapper flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                    <TrendingUp className="aui-sidebar-header-icon size-4" />
                  </div>
                  <div className="aui-sidebar-header-heading me-6 flex flex-col gap-0.5 leading-none">
                    <span className="aui-sidebar-header-title font-semibold">
                      TaiStock
                    </span>
                    <span className="text-xs text-muted-foreground">
                      Terminal
                    </span>
                  </div>
                </a>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </div>
      </SidebarHeader>
      <SidebarContent className="aui-sidebar-content px-2">
        <div className="px-2 pt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Watchlist
        </div>
        <WatchlistPanel />
        <div className="mt-2 border-t px-2 pt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Chats
        </div>
        <ThreadList />
      </SidebarContent>
      <SidebarRail />
      <SidebarFooter className="aui-sidebar-footer border-t">
        <SidebarMenu>
          <SidebarMenuItem>
            <SettingsDialog />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
