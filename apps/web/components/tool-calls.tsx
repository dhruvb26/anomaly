"use client";

import type { AIMessage, ToolMessage } from "@langchain/langgraph-sdk";
import { CheckIcon, ChevronDown, ChevronUp, CopyIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { CollapsibleSection } from "@/components/collapsible-section";
import { useToolDescriptions } from "@/contexts/tool-descriptions-context";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";
import { Skeleton } from "./ui/skeleton";

const MAX_DISPLAY_LEN = 50;

function isComplexValue(value: unknown): boolean {
  return Array.isArray(value) || (typeof value === "object" && value !== null);
}

function truncate(str: string, maxLen = MAX_DISPLAY_LEN): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "...";
}

function CopyCallIdButton({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(id).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <Button variant="ghost" onClick={copy} size="icon" className="size-8">
      {copied ? (
        <CheckIcon className="size-4" />
      ) : (
        <CopyIcon className="size-4" />
      )}
      <span className="sr-only">Copy</span>
    </Button>
  );
}

function ToolResultContent({
  message,
  contentExpanded,
  setContentExpanded,
}: {
  message: ToolMessage;
  contentExpanded: boolean;
  setContentExpanded: (v: boolean) => void;
}) {
  let parsedContent: unknown;
  let isJsonContent = false;

  try {
    if (typeof message.content === "string") {
      parsedContent = JSON.parse(message.content);
      isJsonContent = isComplexValue(parsedContent);
    } else {
      parsedContent = message.content;
    }
  } catch {
    parsedContent = message.content;
  }

  const contentStr = isJsonContent
    ? JSON.stringify(parsedContent, null, 2)
    : String(message.content);
  const contentLines = contentStr.split("\n");
  const shouldTruncate = contentLines.length > 4 || contentStr.length > 500;
  const displayedContent =
    shouldTruncate && !contentExpanded
      ? contentStr.length > 500
        ? contentStr.slice(0, 500) + "..."
        : contentLines.slice(0, 4).join("\n") + "\n..."
      : contentStr;

  const isArray = Array.isArray(parsedContent);
  const arr = parsedContent as unknown[];
  const entries = isJsonContent
    ? isArray
      ? (contentExpanded ? arr : arr.slice(0, 5)).map(
          (item: unknown, i: number) => [i, item] as [number, unknown],
        )
      : Object.entries(parsedContent as Record<string, unknown>)
    : [];

  const showExpandButton =
    (shouldTruncate && !isJsonContent) ||
    (isJsonContent && isArray && arr.length > 5);

  return (
    <div className="flex flex-col">
      {isJsonContent ? (
        entries.map(
          ([key, value]: [string | number, unknown], argIdx: number) => (
            <div key={argIdx}>
              {argIdx > 0 && <div className="border-t border-border mx-4" />}
              <div className="flex px-4 py-2">
                <span className="text-sm text-foreground whitespace-nowrap w-1/4">
                  {String(key)}
                </span>
                <span className="text-sm text-muted-foreground break-all">
                  {isComplexValue(value)
                    ? truncate(JSON.stringify(value, null, 2))
                    : truncate(String(value))}
                </span>
              </div>
            </div>
          ),
        )
      ) : (
        <span className="block px-4 py-2 text-sm text-muted-foreground">
          {displayedContent}
        </span>
      )}
      {showExpandButton && (
        <button
          type="button"
          onClick={() => setContentExpanded(!contentExpanded)}
          className={cn(
            "flex w-full cursor-pointer items-center justify-center py-2.5 text-muted-foreground",
            "transition-colors hover:bg-muted/50 hover:text-foreground",
          )}
        >
          {contentExpanded ? (
            <ChevronUp className="size-5" />
          ) : (
            <ChevronDown className="size-5" />
          )}
        </button>
      )}
    </div>
  );
}

function ToolCallWithResult({
  tc,
  result,
  idx,
}: {
  tc: NonNullable<AIMessage["tool_calls"]>[number];
  result?: ToolMessage;
  idx: number;
}) {
  const [contentExpanded, setContentExpanded] = useState(false);
  const args = (tc.args ?? {}) as Record<string, unknown>;
  const hasArgs = Object.keys(args).length > 0;
  const argEntries = Object.entries(args);

  return (
    <div className="flex flex-col gap-4">
      {hasArgs && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-start gap-2.5">
            <span className="text-sm text-muted-foreground uppercase tracking-wide">
              Request
            </span>
            {tc.id && <CopyCallIdButton id={tc.id} />}
          </div>
          <div className="overflow-hidden rounded-lg border border-border bg-muted/30 min-w-lg">
            <div className="flex flex-col">
              {argEntries.map(([key, value], argIdx) => (
                <div key={argIdx}>
                  {argIdx > 0 && (
                    <div className="border-t border-border mx-4" />
                  )}
                  <div className="flex px-4 py-2">
                    <span className="text-sm text-foreground whitespace-nowrap w-1/4">
                      {key}
                    </span>
                    <span className="text-sm text-muted-foreground break-all">
                      {isComplexValue(value)
                        ? truncate(JSON.stringify(value, null, 2))
                        : truncate(String(value))}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {result ? (
        <div className="flex flex-col gap-2">
          <span className="text-sm text-muted-foreground uppercase tracking-wide">
            Response
          </span>
          <div className="overflow-hidden rounded-lg border border-border bg-muted/30 min-w-lg">
            <ToolResultContent
              message={result}
              contentExpanded={contentExpanded}
              setContentExpanded={setContentExpanded}
            />
          </div>
        </div>
      ) : (
        <div className="flex font-mono text-sm items-center gap-2.5 text-muted-foreground">
          <span className="inline-block size-2.5 rounded-full bg-yellow-500 animate-pulse" />
          RUNNING...
        </div>
      )}
    </div>
  );
}

function ToolDisplayText({
  toolCalls,
}: {
  toolCalls: NonNullable<AIMessage["tool_calls"]>;
}) {
  const { getDescription, isLoading } = useToolDescriptions();

  if (toolCalls.length !== 1) {
    return <span>{toolCalls.length} tools</span>;
  }

  const toolName = toolCalls[0]?.name;
  if (!toolName) return <span>Tool</span>;

  const description = getDescription(toolName);
  const loading = isLoading(toolName);

  if (loading) {
    return <Skeleton className="h-5 w-28" />;
  }

  return <span>{description || toolName}</span>;
}

export function ToolCallGroup({
  toolCalls,
  toolResults,
}: {
  toolCalls: AIMessage["tool_calls"];
  toolResults: ToolMessage[];
}) {
  const { requestDescription } = useToolDescriptions();

  useEffect(() => {
    if (!toolCalls) return;
    for (const tc of toolCalls) {
      if (tc.name) {
        requestDescription(tc.name);
      }
    }
  }, [toolCalls, requestDescription]);

  if (!toolCalls || toolCalls.length === 0) return null;

  const resultMap = new Map<string, ToolMessage>();
  for (const result of toolResults) {
    if (result.tool_call_id) {
      resultMap.set(result.tool_call_id, result);
    }
  }

  return (
    <CollapsibleSection label={<ToolDisplayText toolCalls={toolCalls} />}>
      <div className="flex flex-col gap-3">
        {toolCalls.map((tc, idx) => (
          <ToolCallWithResult
            key={tc.id ?? idx}
            tc={tc}
            result={tc.id ? resultMap.get(tc.id) : undefined}
            idx={idx}
          />
        ))}
      </div>
    </CollapsibleSection>
  );
}
