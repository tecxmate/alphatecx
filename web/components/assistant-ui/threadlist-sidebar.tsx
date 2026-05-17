import { TrendingUp } from "lucide-react";
import type * as React from "react";
import { SettingsDialog } from "@/components/assistant-ui/settings-dialog";
import { ThreadList } from "@/components/assistant-ui/thread-list";
import { WatchlistPanel } from "@/components/assistant-ui/watchlist-panel";
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	SidebarRail,
	SidebarTrigger,
} from "@/components/ui/sidebar";

export function ThreadListSidebar({
	...props
}: React.ComponentProps<typeof Sidebar>) {
	return (
		<Sidebar {...props}>
			<SidebarHeader className="aui-sidebar-header mb-2 border-b">
				<div className="aui-sidebar-header-content flex items-start gap-2">
					<SidebarMenu className="min-w-0 flex-1">
						<SidebarMenuItem>
							<SidebarMenuButton size="lg" asChild>
								<a href="/" rel="noopener noreferrer">
									<div className="aui-sidebar-header-icon-wrapper flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
										<TrendingUp className="aui-sidebar-header-icon size-4" />
									</div>
									<div className="aui-sidebar-header-heading me-6 flex flex-col gap-0.5 leading-none">
										<span
											className="aui-sidebar-header-title text-[28px] italic leading-none text-primary"
											style={{ fontFamily: "var(--font-brand-script)" }}
										>
											tecxstock
										</span>
									</div>
								</a>
							</SidebarMenuButton>
						</SidebarMenuItem>
					</SidebarMenu>
					<SidebarTrigger className="mt-2 shrink-0" />
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
