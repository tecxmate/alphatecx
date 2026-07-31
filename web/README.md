Chat client for the alphatecx v2 MCP server, built on the [assistant-ui](https://github.com/assistant-ui/assistant-ui) MCP starter. It connects to the Python FastMCP server in `../mcp_server/api/index.py` for tools and renders [MCP Apps](https://apps.extensions.modelcontextprotocol.io/) (sandboxed UI widgets attached to tool calls) inline.

Separate app from the Python project: pnpm, and **biome** for lint/format (`pnpm lint` → `biome check .`), not eslint. It is not covered by the repo's `pytest` suite.

## Getting Started

Create `.env.local`:

```
# Full MCP URL including the URL-as-secret token. Required — the client
# throws at startup if unset. Local: http://localhost:8787/mcp/<TOKEN>/mcp
MCP_SERVER_URL=https://<host>/mcp/<MCP_BEARER_TOKEN>/mcp

# Provider defaults to anthropic. Set the key for whichever you use.
ANTHROPIC_API_KEY=...
# LLM_PROVIDER=anthropic | openai | google | deepseek | moonshot | nvidia
# LLM_MODEL=<model-id>
```

Other providers read `OPENAI_API_KEY`, `GOOGLE_*`, `DEEPSEEK_API_KEY`, `KIMI_API_KEY` (or `MOONSHOT_API_KEY`), and `NVIDIA_API_KEY`. Note `deepseek-reasoner` does not support tool calling and is served without tools.

Run the dev server:

```bash
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000).

## How it's wired

- `app/api/mcp-client.ts` — lazy-creates a single `@ai-sdk/mcp` client used by both routes below.
- `app/api/chat/route.ts` — chat route. Pulls tools from the MCP server (`client.tools()`) and forwards them to the model.
- `app/api/mcp-apps/route.ts` — the MCP Apps host route. The renderer POSTs `{ method, params }` here for `mcp-apps/read-resource`, `tools/call`, `resources/read`, and `resources/list`.
- `app/assistant.tsx` — composes `McpAppRenderer({ host: McpAppsRemoteHost({ url: "/api/mcp-apps" }) })` into the `Tools` resource so any tool call whose part carries `mcp.app` metadata renders its widget inline.

When the MCP server attaches a `_meta.ui.resourceUri` (`text/html;profile=mcp-app`) to a tool, AI SDK forwards it through `callProviderMetadata.mcp.app`; `@assistant-ui/react-ai-sdk` lifts it onto `ToolCallMessagePart.mcp.app`; the renderer picks it up and mounts the widget in a sandboxed iframe with a JSON-RPC bridge. See the [MCP Apps guide](https://www.assistant-ui.com/docs/guides/mcp-apps) for the full protocol.
