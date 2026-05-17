import { anthropic } from "@ai-sdk/anthropic";
import { deepseek } from "@ai-sdk/deepseek";
import { google } from "@ai-sdk/google";
import { createOpenAI, openai } from "@ai-sdk/openai";
import { frontendTools } from "@assistant-ui/react-ai-sdk";

// Moonshot (Kimi) speaks the OpenAI protocol — same client, different base.
// Accepts either KIMI_API_KEY or MOONSHOT_API_KEY for env-var ergonomics.
const moonshot = createOpenAI({
  baseURL: "https://api.moonshot.ai/v1",
  apiKey: process.env.KIMI_API_KEY ?? process.env.MOONSHOT_API_KEY,
});

// NVIDIA NIM cloud catalog — OpenAI-compatible. Free tier on build.nvidia.com.
// Model ids use the `org/name` form (e.g. meta/llama-3.3-70b-instruct), which
// is how providerFor() distinguishes NIM from the other providers.
const nvidia = createOpenAI({
  baseURL: "https://integrate.api.nvidia.com/v1",
  apiKey: process.env.NVIDIA_API_KEY,
});

import {
  convertToModelMessages,
  type JSONSchema7,
  type LanguageModel,
  stepCountIs,
  streamText,
  type ToolSet,
  type UIMessage,
} from "ai";
import { getMcpTools } from "../mcp-client";

export const maxDuration = 60;

const SYSTEM_PROMPT = `You are a Taiwanese quantitative analyst assisting a researcher who covers the Taiwan Stock Exchange (TWSE) and TPEx.

Rules:
- Use tools when database-backed facts are needed, but keep tool use disciplined.
- Use at most one tool call unless additional data is clearly required.
- Prefer the narrowest tool that answers the question.
- Do not call tools to restate already available context.
- After receiving sufficient tool data, answer immediately.
- TWSE tickers are 4-digit codes (e.g. 2330, 6488). Validate before querying. If the user gives a company name, ask which ticker they mean unless it is unambiguous.
- Every tool response includes \`_source\`, \`_as_of\`, and \`_freshness\`. Cite these in your reply so the user can judge data freshness.
- Be concise. Lead with the answer. Show your reasoning only when the user asks.
- When tool data is stale or missing, say so plainly — never invent numbers.`;

// deepseek-reasoner does not support tool/function calling. If we pass tools
// the request errors. Track this so we strip MCP tools on reasoner turns.
const NO_TOOL_MODELS = new Set(["deepseek-reasoner"]);

// Infer provider from the model id prefix so the client only has to send a
// single string (the assistant-ui ModelSelector ships `config.modelName`).
function providerFor(
  modelId: string,
): "google" | "deepseek" | "moonshot" | "openai" | "nvidia" | "anthropic" {
  // NIM model ids use org/name format (meta/llama..., mistralai/..., etc.)
  // Catch them first so deepseek-ai/* doesn't get routed to DeepSeek's own API.
  if (modelId.includes("/")) return "nvidia";
  if (modelId.startsWith("gemini")) return "google";
  if (modelId.startsWith("deepseek")) return "deepseek";
  if (modelId.startsWith("kimi") || modelId.startsWith("moonshot"))
    return "moonshot";
  if (
    modelId.startsWith("gpt-") ||
    modelId.startsWith("o3") ||
    modelId.startsWith("o4")
  )
    return "openai";
  return "anthropic";
}

function selectModel(requested?: string): {
  model: LanguageModel;
  supportsTools: boolean;
} {
  // Priority: explicit request from client → env default → anthropic fallback.
  const envProvider = (process.env.LLM_PROVIDER ?? "anthropic").toLowerCase();
  const envModel = process.env.LLM_MODEL;
  const modelId =
    requested ??
    envModel ??
    (envProvider === "google"
      ? "gemini-2.5-flash"
      : envProvider === "deepseek"
        ? "deepseek-reasoner"
        : envProvider === "moonshot"
          ? "kimi-k2.6"
          : envProvider === "openai"
            ? "gpt-5-mini"
            : "claude-sonnet-4-5");
  const provider = providerFor(modelId);
  if (provider === "google") {
    return { model: google(modelId), supportsTools: true };
  }
  if (provider === "deepseek") {
    return {
      model: deepseek(modelId),
      supportsTools: !NO_TOOL_MODELS.has(modelId),
    };
  }
  if (provider === "moonshot") {
    // Moonshot exposes Chat Completions only; AI SDK's openai() now defaults
    // to the Responses API, so we have to opt into .chat() explicitly.
    return { model: moonshot.chat(modelId), supportsTools: true };
  }
  if (provider === "openai") {
    return { model: openai(modelId), supportsTools: true };
  }
  if (provider === "nvidia") {
    // NIM is Chat Completions only — same opt-in as Moonshot.
    return { model: nvidia.chat(modelId), supportsTools: true };
  }
  return { model: anthropic(modelId), supportsTools: true };
}

async function loadMcpTools(): Promise<ToolSet> {
  try {
    return await getMcpTools();
  } catch (e) {
    console.warn("Failed to connect to MCP server:", e);
    return {};
  }
}

function getMaxToolSteps(): number {
  const raw = process.env.MAX_TOOL_STEPS;
  if (!raw) return 3;

  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed)) return 3;

  return Math.min(Math.max(parsed, 1), 10);
}

export async function POST(req: Request) {
  const {
    messages,
    system,
    tools,
    config,
  }: {
    messages: UIMessage[];
    system?: string;
    tools?: Record<string, { description?: string; parameters: JSONSchema7 }>;
    config?: { modelName?: string };
  } = await req.json();

  const { model, supportsTools } = selectModel(config?.modelName);
  const mcpTools = supportsTools ? await loadMcpTools() : {};
  const frontend = supportsTools ? frontendTools(tools ?? {}) : {};

  const result = streamText({
    model,
    messages: await convertToModelMessages(messages),
    system: system ?? SYSTEM_PROMPT,
    tools: { ...mcpTools, ...frontend },
    stopWhen: stepCountIs(getMaxToolSteps()),
  });

  return result.toUIMessageStreamResponse({
    sendReasoning: true,
  });
}
