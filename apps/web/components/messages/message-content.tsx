import type { Message } from "@langchain/langgraph-sdk";

export function getContentString(content: Message["content"]): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter(
        (block): block is { type: "text"; text: string } =>
          typeof block === "object" &&
          block !== null &&
          "type" in block &&
          block.type === "text",
      )
      .map((block) => block.text)
      .join("\n");
  }
  return "";
}

export function getThinkingBlocks(content: Message["content"]): string[] {
  if (!Array.isArray(content)) return [];
  const results: string[] = [];
  for (const block of content) {
    const b = block as Record<string, unknown>;
    if (b["type"] === "thinking" && typeof b["thinking"] === "string") {
      const thinking = b["thinking"];
      if (thinking.trim().length > 0) results.push(thinking);
    }
  }
  return results;
}
