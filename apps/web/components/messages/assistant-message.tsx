"use client";

import type { Message, ToolMessage } from "@langchain/langgraph-sdk";
import { ArrowRight } from "lucide-react";
import { CollapsibleSection } from "@/components/collapsible-section";
import { MarkdownText } from "@/components/markdown-text";
import { ToolCallGroup } from "@/components/tool-calls";
import { cn } from "@/lib/utils";
import { ExtendedThinkingBlock } from "./extended-thinking-block";
import { getContentString, getThinkingBlocks } from "./message-content";

const AGENT_LABELS: Record<string, { label: string; color: string }> = {
  orchestrator: {
    label: "Orchestrator",
    color: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  },
  file_surfer: {
    label: "FileSurfer",
    color: "bg-sky-500/15 text-sky-700 dark:text-sky-400",
  },
  web_surfer: {
    label: "WebSurfer",
    color: "bg-lime-500/15 text-lime-700 dark:text-lime-400",
  },
  code_executor: {
    label: "CodeExecutor",
    color: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  },
};

function AgentBadge({ name }: { name: string }) {
  const badge = AGENT_LABELS[name];
  if (!badge) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center w-fit rounded-md px-2.5 py-1 text-sm font-medium",
        badge.color,
      )}
    >
      {badge.label}
    </span>
  );
}

interface OrchestratorDecision {
  thought: string;
  next_agent: "file_surfer" | "web_surfer" | "code_executor" | "FINISH";
  instruction: string;
}

function OrchestratorDecisionBlock({
  decision,
  extendedThoughts,
}: {
  decision: OrchestratorDecision;
  extendedThoughts?: string[];
}) {
  const isFinish = decision.next_agent === "FINISH";
  const targetBadge = !isFinish ? AGENT_LABELS[decision.next_agent] : null;

  return (
    <div className="flex justify-start w-full">
      <div className="max-w-[80%] flex flex-col gap-3 w-full">
        <div className="flex items-center gap-2 flex-wrap">
          <AgentBadge name="orchestrator" />
          {!isFinish && targetBadge && (
            <>
              <ArrowRight className="size-4 text-muted-foreground" />
              <AgentBadge name={decision.next_agent} />
            </>
          )}
          {isFinish && (
            <>
              <ArrowRight className="size-4 text-muted-foreground" />
              <span className="inline-flex items-center rounded-md px-2.5 py-1 text-sm font-medium bg-zinc-500/15 text-zinc-700 dark:text-zinc-400">
                Final Answer
              </span>
            </>
          )}
        </div>

        {extendedThoughts && extendedThoughts.length > 0 && (
          <ExtendedThinkingBlock thoughts={extendedThoughts} />
        )}

        {decision.thought && (
          <CollapsibleSection label="Thought">
            <p className="whitespace-pre-wrap text-base leading-relaxed text-muted-foreground/70">
              {decision.thought}
            </p>
          </CollapsibleSection>
        )}

        {decision.instruction &&
          (isFinish ? (
            <MarkdownText>{decision.instruction}</MarkdownText>
          ) : (
            <div className="px-4 py-3 text-base text-muted-foreground border border-border rounded-md">
              {decision.instruction}
            </div>
          ))}
      </div>
    </div>
  );
}

interface AssistantMessageBubbleProps {
  message: Message;
  toolResults: ToolMessage[];
}

export function AssistantMessageBubble({
  message,
  toolResults,
}: AssistantMessageBubbleProps) {
  const content = getContentString(message.content);
  const thoughts = getThinkingBlocks(message.content);
  const hasToolCalls =
    message.type === "ai" &&
    "tool_calls" in message &&
    message.tool_calls &&
    message.tool_calls.length > 0;

  const agentName =
    "name" in message && typeof message.name === "string" ? message.name : null;

  const additionalKwargs =
    "additional_kwargs" in message && message.additional_kwargs
      ? (message.additional_kwargs as Record<string, unknown>)
      : null;
  const isOrchestratorDecision =
    agentName === "orchestrator" && additionalKwargs?.routing;

  if (isOrchestratorDecision) {
    const decision: OrchestratorDecision = {
      thought: String(additionalKwargs.thought ?? ""),
      next_agent:
        additionalKwargs.routing as OrchestratorDecision["next_agent"],
      instruction: content,
    };
    return (
      <OrchestratorDecisionBlock
        decision={decision}
        extendedThoughts={thoughts}
      />
    );
  }

  const showContent = content.trim().length > 0;
  const showToolCalls = hasToolCalls;

  if (!showContent && !showToolCalls && thoughts.length === 0) return null;

  const badge = agentName ? AGENT_LABELS[agentName] : null;

  return (
    <div className="flex justify-start w-full">
      <div className="max-w-[80%] flex flex-col gap-3">
        {badge && <AgentBadge name={agentName!} />}
        {thoughts.length > 0 && <ExtendedThinkingBlock thoughts={thoughts} />}
        {showContent && <MarkdownText>{content}</MarkdownText>}
        {showToolCalls && message.tool_calls && (
          <ToolCallGroup
            toolCalls={message.tool_calls}
            toolResults={toolResults}
          />
        )}
      </div>
    </div>
  );
}
