import type { Message } from "@langchain/langgraph-sdk";
import { getContentString } from "./message-content";

interface HumanMessageBubbleProps {
  message: Message;
}

export function HumanMessageBubble({ message }: HumanMessageBubbleProps) {
  const content = getContentString(message.content);
  if (!content.trim()) return null;

  return (
    <div className="flex justify-end w-full">
      <div className="max-w-[80%] px-4 py-3 text-base leading-relaxed whitespace-pre-wrap text-foreground bg-muted rounded-xl">
        {content}
      </div>
    </div>
  );
}
