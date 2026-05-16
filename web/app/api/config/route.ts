import { getMcpClient } from "../mcp-client";

export const revalidate = 30;

function redactToken(url?: string): string {
  if (!url) return "(not set)";
  return url.replace(/\/mcp\/[^/]+/, "/mcp/<token>");
}

export async function GET() {
  const provider = (process.env.LLM_PROVIDER ?? "anthropic").toLowerCase();
  const model =
    process.env.LLM_MODEL ??
    (provider === "deepseek"
      ? "deepseek-reasoner"
      : provider === "google"
        ? "gemini-2.5-flash"
        : "claude-sonnet-4-5");

  let mcpStatus: "ok" | "error" = "ok";
  let mcpToolCount = 0;
  let mcpError: string | undefined;
  try {
    const client = await getMcpClient();
    const tools = await client.tools();
    mcpToolCount = Object.keys(tools).length;
  } catch (e) {
    mcpStatus = "error";
    mcpError = String(e).slice(0, 200);
  }

  return Response.json({
    provider,
    model,
    mcp: {
      url: redactToken(process.env.MCP_SERVER_URL),
      status: mcpStatus,
      toolCount: mcpToolCount,
      error: mcpError,
    },
  });
}
