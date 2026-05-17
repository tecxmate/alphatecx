import {
  experimental_createMCPClient as createMCPClient,
  type MCPClient,
} from "@ai-sdk/mcp";
import type { ToolSet } from "ai";

// Points at the Python FastMCP server in mcp_server/api/index.py.
// Auth is URL-as-secret: the full path is /mcp/<TOKEN>/mcp (streamable_http
// mounts at /mcp inside the token-scoped FastAPI mount). Set MCP_SERVER_URL
// to the full URL including the secret.
let mcpClientPromise: ReturnType<typeof createMCPClient> | null = null;
let cachedTools: ToolSet | null = null;

const DEFAULT_TOOL_CACHE_TTL_MS = 60_000;
const CACHEABLE_TOOL_NAMES = new Set([
  "w_watchlist",
  "q_regime",
  "n_recent",
  "n_for_ticker",
  "q_indicators",
  "sc_ticker_momentum",
  "raw_flow_history",
  "sc_accumulation_screen",
  "sc_supply_chain_map",
]);

type ExecutableTool = {
  execute?: (input: unknown, options: unknown) => Promise<unknown>;
};

type ToolCacheEntry = {
  expiresAt: number;
  value: unknown;
};

const toolResultCache = new Map<string, ToolCacheEntry>();

function getToolCacheTtlMs(): number {
  const raw = process.env.MCP_TOOL_CACHE_TTL_SECONDS;
  if (!raw) return DEFAULT_TOOL_CACHE_TTL_MS;

  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return 0;

  return Math.min(parsed, 300) * 1000;
}

function stableStringify(value: unknown): string {
  if (value === undefined) return "undefined";
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value) ?? String(value);
  }
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;

  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`)
    .join(",")}}`;
}

function cacheMcpToolResults(tools: ToolSet): ToolSet {
  const ttlMs = getToolCacheTtlMs();
  if (ttlMs <= 0) return tools;

  return Object.fromEntries(
    Object.entries(tools).map(([name, tool]) => {
      const executable = tool as ExecutableTool;
      if (!CACHEABLE_TOOL_NAMES.has(name) || !executable.execute) {
        return [name, tool];
      }

      return [
        name,
        {
          ...tool,
          async execute(input: unknown, options: unknown) {
            const key = `${name}:${stableStringify(input)}`;
            const now = Date.now();
            const cached = toolResultCache.get(key);
            if (cached && cached.expiresAt > now) return cached.value;

            const value = await executable.execute?.(input, options);
            toolResultCache.set(key, { value, expiresAt: now + ttlMs });
            return value;
          },
        },
      ];
    }),
  ) as ToolSet;
}

export function getMcpClient(): Promise<MCPClient> {
  const url = process.env.MCP_SERVER_URL;
  if (!url) {
    throw new Error(
      "MCP_SERVER_URL is not set. Expected e.g. https://<host>/mcp/<token>/mcp",
    );
  }
  mcpClientPromise ??= createMCPClient({
    transport: { type: "http", url },
  });
  return mcpClientPromise;
}

export async function getMcpTools(): Promise<ToolSet> {
  if (cachedTools) return cachedTools;
  const client = await getMcpClient();
  cachedTools = cacheMcpToolResults((await client.tools()) as ToolSet);
  return cachedTools;
}
