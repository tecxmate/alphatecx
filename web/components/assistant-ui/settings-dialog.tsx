"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { SidebarMenuButton } from "@/components/ui/sidebar";
import { SettingsIcon } from "lucide-react";
import { useEffect, useState } from "react";

type Config = {
  provider: string;
  model: string;
  mcp: {
    url: string;
    status: "ok" | "error";
    toolCount: number;
    error?: string;
  };
};

export function SettingsDialog() {
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    fetch("/api/config")
      .then((r) => r.json())
      .then(setCfg)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (open && !cfg) load();
  }, [open, cfg]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <SidebarMenuButton size="lg">
          <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
            <SettingsIcon className="size-4" />
          </div>
          <div className="flex flex-col gap-0.5 leading-none">
            <span className="font-semibold">Settings</span>
            <span className="text-xs text-muted-foreground">
              Model & MCP status
            </span>
          </div>
        </SidebarMenuButton>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Runtime configuration for this session. Change env vars in
            <code className="mx-1 rounded bg-muted px-1 text-xs">.env.local</code>
            and restart the dev server to update.
          </DialogDescription>
        </DialogHeader>

        {loading && !cfg && (
          <div className="py-4 text-sm text-muted-foreground">Loading…</div>
        )}

        {cfg && (
          <div className="space-y-4 text-sm">
            <Section title="Language model">
              <Row label="Provider" value={cfg.provider} />
              <Row label="Model" value={cfg.model} mono />
            </Section>

            <Section title="MCP server">
              <Row
                label="Status"
                value={
                  <span
                    className={
                      cfg.mcp.status === "ok"
                        ? "rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                        : "rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800 dark:bg-red-950 dark:text-red-300"
                    }
                  >
                    {cfg.mcp.status === "ok" ? "connected" : "error"}
                  </span>
                }
              />
              <Row label="Tools" value={String(cfg.mcp.toolCount)} mono />
              <Row label="URL" value={cfg.mcp.url} mono />
              {cfg.mcp.error && (
                <div className="mt-2 rounded border border-red-300 bg-red-50 p-2 text-xs text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
                  {cfg.mcp.error}
                </div>
              )}
            </Section>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={load}
                className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-muted"
              >
                Refresh
              </button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <div className="space-y-1 rounded-md border bg-card p-2">{children}</div>
    </div>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={`truncate text-right ${mono ? "font-mono text-xs" : ""}`}
      >
        {value}
      </span>
    </div>
  );
}
