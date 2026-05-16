---
title: Build the chat frontend with assistant-ui (Next.js) over the existing Python MCP
type: decision
slug: 2026-05-17-assistant-ui-frontend
date: 2026-05-17
attributed_to: [niko]
belongs_to: [system-architecture, web-frontend]
source: chat
status: active
tags: [frontend, nextjs, assistant-ui, ai-sdk, anthropic, mcp]
related: [system-architecture, 2026-05-07-neon-over-supabase]
---

## Context

A Gemini-authored spec ("TECXMATE AI Terminal") proposed a full Next.js + Vercel AI SDK + Anthropic + Stripe + Clerk frontend with a new Node MCP server and AWS App Runner. Most of that backend (MCP server, Neon schema, ETL) is already done in Python. The real gap was a conversational frontend — the existing UI is the static dashboard at `mcp_server/api/static/` plus a Telegram bot.

## Decision

Scaffold a Next.js 15 app at `web/` using `npx assistant-ui@latest create web --template mcp`. Wire `/api/chat` to Anthropic via the AI SDK and connect to the **existing Python FastMCP server** via `experimental_createMCPClient` over streamable HTTP. The frontend never talks to Neon directly — all data flows through MCP tools.

Generative UI for three high-signal tools out of the box:

| MCP tool | Component | Library |
|---|---|---|
| `raw_flow_history` | `ChipFlowChartUI` | Recharts bar chart |
| `sc_accumulation_screen` | `ScreenerTableUI` | TanStack Table |
| `sc_supply_chain_map` | `SupplyChainListUI` | Grouped chips (deferred React Flow for v2) |

## Why

- **Reuse over rebuild.** Re-implementing the MCP server in Node duplicates ~1,200 lines of working Python and forks the tool surface. The AI SDK MCP client talks to any compliant server.
- **assistant-ui's `mcp` template** ships the runtime, sidebar, thread list, and tool-fallback wiring — zero custom orchestration code.
- **URL-as-secret auth** the Python server already uses (`/mcp/<TOKEN>/mcp`) works unmodified — no Authorization header plumbing.

## How to apply

- All new tools the Python MCP exposes are picked up automatically by the chat without code changes.
- To add generative UI for a new tool, create a component with `makeAssistantToolUI({ toolName, render })` in `web/components/tools/` and mount it inside `<AssistantRuntimeProvider>` in `web/app/assistant.tsx`.
- Model defaults to `claude-sonnet-4-5`, overridable via `ANTHROPIC_MODEL` env var. Workspace convention is `claude-sonnet-4-6` for production.

## Out of scope for v1

- Clerk auth, Stripe metered billing, 20-prompt gatekeeper (Gemini spec §5) — deferred.
- Replacing the static dashboard at `mcp_server/api/static/` — coexists.
- PWA manifest, chat history persistence to Neon — deferred until auth lands.
- React Flow for supply chain — deferred; flat grouped list is sufficient for v1.

## Risks

- **Vercel function duration.** Multi-step tool chains can exceed hobby 10s. Set `maxDuration = 60`; may need Pro plan or Edge runtime later.
- **Model ID drift.** AI SDK Anthropic provider model strings change; pinning to env var (`ANTHROPIC_MODEL`) lets us roll forward without code changes.
