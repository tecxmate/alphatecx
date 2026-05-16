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
  cachedTools = (await client.tools()) as ToolSet;
  return cachedTools;
}
