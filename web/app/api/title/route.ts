import { anthropic } from "@ai-sdk/anthropic";
import { deepseek } from "@ai-sdk/deepseek";
import { google } from "@ai-sdk/google";
import { generateText, type LanguageModel } from "ai";

export const maxDuration = 15;

function selectModel(): LanguageModel {
  const provider = (process.env.LLM_PROVIDER ?? "anthropic").toLowerCase();
  const id = process.env.LLM_MODEL;
  if (provider === "deepseek") return deepseek(id ?? "deepseek-chat");
  if (provider === "google") return google(id ?? "gemini-2.5-flash");
  return anthropic(id ?? "claude-sonnet-4-5");
}

export async function POST(req: Request) {
  const { message }: { message: string } = await req.json();
  if (!message?.trim()) {
    return Response.json({ title: "" });
  }
  try {
    const { text } = await generateText({
      model: selectModel(),
      prompt: `Generate a 3-6 word title for this chat. No quotes, no punctuation at the end. Just the title.\n\nUser's first message:\n${message.slice(0, 500)}`,
    });
    const title = text.replace(/^["'`]+|["'`.]+$/g, "").trim().slice(0, 80);
    return Response.json({ title });
  } catch (e) {
    return Response.json({ title: "", error: String(e).slice(0, 200) });
  }
}
