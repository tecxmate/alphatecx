import { anthropic } from "@ai-sdk/anthropic";
import { deepseek } from "@ai-sdk/deepseek";
import { google } from "@ai-sdk/google";
import { frontendTools } from "@assistant-ui/react-ai-sdk";
import {
  type JSONSchema7,
  type LanguageModel,
  type ToolSet,
  type UIMessage,
  convertToModelMessages,
  streamText,
} from "ai";
import { getMcpTools } from "../mcp-client";

export const maxDuration = 60;

const SYSTEM_PROMPT = `You are a Taiwanese quantitative analyst assisting a researcher who covers the Taiwan Stock Exchange (TWSE) and TPEx.

Rules:
- Prefer tool calls over assertions. If a claim can be checked against the database, check it.
- TWSE tickers are 4-digit codes (e.g. 2330, 6488). Validate before querying. If the user gives a company name, ask which ticker they mean unless it is unambiguous.
- Every tool response includes \`_source\`, \`_as_of\`, and \`_freshness\`. Cite these in your reply so the user can judge data freshness.
- Be concise. Lead with the answer. Show your reasoning only when the user asks.
- When tool data is stale or missing, say so plainly — never invent numbers.`;

// deepseek-reasoner does not support tool/function calling. If we pass tools
// the request errors. Track this so we strip MCP tools on reasoner turns.
const NO_TOOL_MODELS = new Set(["deepseek-reasoner"]);

function selectModel(): { model: LanguageModel; supportsTools: boolean } {
  const provider = (process.env.LLM_PROVIDER ?? "anthropic").toLowerCase();
  const id = process.env.LLM_MODEL;
  if (provider === "deepseek") {
    const modelId = id ?? "deepseek-reasoner";
    return {
      model: deepseek(modelId),
      supportsTools: !NO_TOOL_MODELS.has(modelId),
    };
  }
  if (provider === "google") {
    return {
      model: google(id ?? "gemini-2.5-flash"),
      supportsTools: true,
    };
  }
  return {
    model: anthropic(id ?? "claude-sonnet-4-5"),
    supportsTools: true,
  };
}

async function loadMcpTools(): Promise<ToolSet> {
  try {
    return await getMcpTools();
  } catch (e) {
    console.warn("Failed to connect to MCP server:", e);
    return {};
  }
}

export async function POST(req: Request) {
  const {
    messages,
    system,
    tools,
  }: {
    messages: UIMessage[];
    system?: string;
    tools?: Record<string, { description?: string; parameters: JSONSchema7 }>;
  } = await req.json();

  const { model, supportsTools } = selectModel();
  const mcpTools = supportsTools ? await loadMcpTools() : {};
  const frontend = supportsTools ? frontendTools(tools ?? {}) : {};

  const result = streamText({
    model,
    messages: await convertToModelMessages(messages),
    system: system ?? SYSTEM_PROMPT,
    tools: { ...mcpTools, ...frontend },
  });

  return result.toUIMessageStreamResponse({
    sendReasoning: true,
  });
}
