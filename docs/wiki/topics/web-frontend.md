---
title: Web frontend (Next.js + assistant-ui)
type: topic
slug: web-frontend
date: 2026-05-17
attributed_to: [niko, antigravity-agent]
belongs_to: [alphatecx, system-architecture]
source: chat
status: active
tags: [frontend, nextjs, assistant-ui, ai-sdk, anthropic]
related: [system-architecture, 2026-05-17-assistant-ui-frontend]
---

## Summary

`web/` is a Next.js 15 app scaffolded from `assistant-ui@latest create --template mcp`. It is a conversational frontend over the existing Python FastMCP server.

## Layout

```
web/
├── app/
│   ├── api/
│   │   ├── chat/route.ts       # Anthropic + AI SDK + MCP tools
│   │   ├── mcp-client.ts       # singleton MCP client (streamable HTTP)
│   │   └── mcp-apps/route.ts   # MCP Apps bridge (template default)
│   ├── assistant.tsx           # AssistantRuntimeProvider + tool UIs
│   └── page.tsx
├── components/
│   ├── assistant-ui/           # template-shipped chat primitives
│   ├── tools/                  # custom generative UI per MCP tool
│   │   ├── chip-flow-chart.tsx       # raw_flow_history
│   │   ├── screener-table.tsx        # sc_accumulation_screen
│   │   ├── supply-chain-list.tsx     # sc_supply_chain_map
│   │   └── provenance.tsx            # _source / _as_of / _freshness chips
│   └── ui/                     # shadcn primitives
└── .env.example
```

## Env

- `LLM_PROVIDER` — `anthropic` (default) or `deepseek`.
- `LLM_MODEL` — provider-specific model id. Defaults: Anthropic → `claude-sonnet-4-5`; DeepSeek → `deepseek-reasoner`.
- `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` — set whichever provider you use.
- `MCP_SERVER_URL` — full URL to the FastMCP streamable HTTP endpoint, including the URL-as-secret token: `http://localhost:8000/mcp/<MCP_BEARER_TOKEN>/mcp` (or prod equivalent).

### Reasoner caveat

`deepseek-reasoner` (R1) does not support tool/function calling. The chat route strips MCP tools when the reasoner is selected, so the model cannot query the TWSE database. Use `deepseek-chat` (V3.2) or Anthropic for tool-using turns; use the reasoner only for pure-reasoning Q&A.

## How a turn flows

1. User types in the assistant-ui `<Thread>` → POST `/api/chat`.
2. Route loads MCP tools (cached singleton) → calls `streamText` with Anthropic Sonnet + tools.
3. Model may call any MCP tool (`sc_*`, `raw_*`, `q_*`, etc.). Tool results stream back as UI parts.
4. For the three tools above, a registered `makeAssistantToolUI` intercepts the part and renders the React component instead of the fallback JSON dump.
5. Every component renders a `<ProvenanceFooter>` with `_source`, `_as_of`, `_freshness` so users can judge data freshness.

## Adding a new generative UI

1. Create `web/components/tools/<name>.tsx` exporting a `makeAssistantToolUI({ toolName, render })`.
2. Import and mount it inside `<AssistantRuntimeProvider>` in `web/app/assistant.tsx`.
3. No backend changes — the Python MCP tool surface is the contract.

## Deploy

Second Vercel project, root directory `web/`. Build command auto-detected. Env vars set in Vercel dashboard. The Python MCP stays on its own Vercel project; the two only communicate over HTTPS via the URL-as-secret endpoint.
