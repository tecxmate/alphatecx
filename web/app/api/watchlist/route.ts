import { getMcpClient } from "../mcp-client";

export const revalidate = 60;

type WatchlistRow = {
  ticker_id?: string;
  name?: string;
  reason?: string;
  status?: string;
  added_at?: string;
};

export async function GET() {
  try {
    const client = await getMcpClient();
    const tools = await client.tools();
    const tool = (tools as Record<string, { execute?: Function }>).w_watchlist;
    if (!tool?.execute) {
      return Response.json({ error: "w_watchlist tool not available" }, { status: 502 });
    }
    const out = await tool.execute(
      { status: "active" },
      { toolCallId: `watchlist-sidebar-${Date.now()}`, messages: [] },
    );
    // MCP tools return CallToolResult; the actual payload is in content[0].text as JSON.
    let payload: { watchlist?: WatchlistRow[]; count?: number } = {};
    if (out && typeof out === "object" && Array.isArray((out as any).content)) {
      const part = (out as any).content[0];
      if (part?.type === "text" && typeof part.text === "string") {
        try {
          payload = JSON.parse(part.text);
        } catch {
          // fall through; payload stays empty
        }
      }
    } else if (out && typeof out === "object") {
      payload = out as any;
    }
    return Response.json({
      watchlist: payload.watchlist ?? [],
      count: payload.count ?? payload.watchlist?.length ?? 0,
    });
  } catch (e) {
    console.warn("watchlist route failed:", e);
    return Response.json({ watchlist: [], count: 0, error: String(e) }, { status: 200 });
  }
}
