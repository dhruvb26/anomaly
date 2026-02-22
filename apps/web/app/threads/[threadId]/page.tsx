"use client";

import type { Message, ToolMessage } from "@langchain/langgraph-sdk";
import { useRealtimeRun } from "@trigger.dev/react-hooks";
import { XCircle } from "lucide-react";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { v4 as uuidv4 } from "uuid";
import { triggerThreadNameGeneration } from "@/actions/generate-thread-name";
import { ChatComposer } from "@/components/composer/chat-composer";
import {
  AssistantMessageBubble,
  getContentString,
  HumanMessageBubble,
} from "@/components/messages";
import { MyLoader } from "@/components/ui/my-loader";
import { useThreadRefresh } from "@/contexts/sidebar-context";
import { env } from "@/env";
import { useChatStream } from "@/hooks/use-chat-stream";
import type { generateThreadNameTask } from "@/trigger/generate-thread-name";

const NvlGraph = dynamic(
  () => import("@/components/graph/nvl-graph").then((m) => m.NvlGraph),
  {
    ssr: false,
  },
);

function NamingTaskSubscriber({
  runId,
  accessToken,
  onComplete,
}: {
  runId: string;
  accessToken: string;
  onComplete: () => void;
}) {
  const { run, error } = useRealtimeRun<typeof generateThreadNameTask>(runId, {
    accessToken,
  });

  useEffect(() => {
    if (run?.status === "COMPLETED") {
      onComplete();
    }
  }, [run?.status, onComplete]);

  useEffect(() => {
    if (error) {
      console.error("Realtime subscription error:", error);
    }
  }, [error]);

  return null;
}

function MessageList({
  messages,
  isLoading,
}: {
  messages: Message[];
  isLoading: boolean;
}) {
  const toolResultsByCallId = new Map<string, ToolMessage>();
  for (const m of messages) {
    if (m.type === "tool" && "tool_call_id" in m && m.tool_call_id) {
      toolResultsByCallId.set(m.tool_call_id, m as ToolMessage);
    }
  }

  const visibleMessages = messages.filter((m) => {
    if (m.type === "human") {
      // Orchestrator HumanMessages are routing artifacts for sub-agents;
      // their instruction is shown inside the OrchestratorDecisionBlock.
      if ("name" in m && m.name === "orchestrator") return false;
      return true;
    }
    if (m.type === "ai") {
      const text = getContentString(m.content);
      const hasToolCalls =
        "tool_calls" in m && m.tool_calls && m.tool_calls.length > 0;
      return text.trim().length > 0 || hasToolCalls;
    }
    return false;
  });

  return (
    <>
      {visibleMessages.map((message, index) => {
        if (message.type === "human") {
          return (
            <HumanMessageBubble
              key={message.id || `human-${index}`}
              message={message}
            />
          );
        }

        const toolCalls =
          "tool_calls" in message ? message.tool_calls : undefined;
        const toolResults: ToolMessage[] = [];
        if (toolCalls) {
          for (const tc of toolCalls) {
            if (tc.id) {
              const result = toolResultsByCallId.get(tc.id);
              if (result) toolResults.push(result);
            }
          }
        }

        return (
          <AssistantMessageBubble
            key={message.id || `ai-${index}`}
            message={message}
            toolResults={toolResults}
          />
        );
      })}
      {isLoading && (
        <div className="flex items-center gap-3">
          <MyLoader />
        </div>
      )}
    </>
  );
}

function StreamErrorBanner({
  error,
  onDismiss,
}: {
  error: unknown;
  onDismiss: () => void;
}) {
  const message = (() => {
    if (error instanceof Error) return error.message;
    if (typeof error === "string") return error;
    if (
      error &&
      typeof error === "object" &&
      "message" in error &&
      typeof (error as { message: unknown }).message === "string"
    )
      return (error as { message: string }).message;
    return "Something went wrong while running the agent.";
  })();

  const isTokenLimit =
    message.includes("prompt is too long") || message.includes("token");
  const isRecursion = message.includes("Recursion limit");

  return (
    <div className="mx-6 mb-4 flex items-start gap-4 rounded-lg border border-destructive/30 bg-destructive/5 px-5 py-4">
      <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
      <div className="flex-1 min-w-0">
        <p className="text-base font-medium text-destructive">Agent Error</p>
        <p className="mt-1.5 text-sm text-muted-foreground wrap-break-word">
          {isTokenLimit
            ? "The context window limit was exceeded. Try starting a new thread."
            : isRecursion
              ? "The agent hit the maximum step limit. The partial results are shown above."
              : String(message)}
        </p>
      </div>
      <button
        onClick={onDismiss}
        className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
      >
        <XCircle className="h-4 w-4" />
      </button>
    </div>
  );
}

export default function ThreadPage() {
  const params = useParams<{ threadId: string }>();
  const threadId = params.threadId;
  const { refreshThreads } = useThreadRefresh();

  const stream = useChatStream(threadId);
  const messages = stream.messages;
  const isLoading = stream.isLoading;
  const isThreadLoading = stream.isThreadLoading;
  const error = stream.error;

  const scrollRef = useRef<HTMLDivElement>(null);
  const sentInitialRef = useRef(false);
  const nameGenerationTriggeredRef = useRef(false);
  const isNewConversationRef = useRef(false);
  const [namingTask, setNamingTask] = useState<{
    runId: string;
    publicAccessToken: string;
  }>();
  const [dismissedError, setDismissedError] = useState(false);
  const [graphData, setGraphData] = useState<{
    nodes: { id: string; [key: string]: unknown }[];
    edges: { id: string; from: string; to: string; [key: string]: unknown }[];
  } | null>(null);

  const graphRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchGraph = useCallback(() => {
    const apiUrl = env.NEXT_PUBLIC_LANGSMITH_API_URL;
    if (!threadId || !apiUrl) return;
    fetch(`${apiUrl}/threads/${threadId}/graph`)
      .then((res) =>
        res.ok ? res.json() : Promise.reject(new Error(`${res.status}`)),
      )
      .then((data: { nodes?: unknown[]; edges?: unknown[] }) => {
        setGraphData({
          nodes: Array.isArray(data.nodes)
            ? (data.nodes as { id: string; [key: string]: unknown }[])
            : [],
          edges: Array.isArray(data.edges)
            ? (data.edges as {
                id: string;
                from: string;
                to: string;
                [key: string]: unknown;
              }[])
            : [],
        });
      })
      .catch(() => setGraphData(null));
  }, [threadId]);

  const fetchGraphWithRetry = useCallback(() => {
    if (graphRetryRef.current) clearTimeout(graphRetryRef.current);
    let attempt = 0;
    const maxRetries = 4;
    const poll = () => {
      const apiUrl = env.NEXT_PUBLIC_LANGSMITH_API_URL;
      if (!threadId || !apiUrl) return;
      fetch(`${apiUrl}/threads/${threadId}/graph`)
        .then((res) =>
          res.ok ? res.json() : Promise.reject(new Error(`${res.status}`)),
        )
        .then((data: { nodes?: unknown[]; edges?: unknown[] }) => {
          const nodes = Array.isArray(data.nodes)
            ? (data.nodes as { id: string; [key: string]: unknown }[])
            : [];
          const edges = Array.isArray(data.edges)
            ? (data.edges as {
                id: string;
                from: string;
                to: string;
                [key: string]: unknown;
              }[])
            : [];
          const hasContent = nodes.length > 0;
          if (hasContent || attempt >= maxRetries) {
            setGraphData({ nodes, edges });
          } else {
            attempt++;
            graphRetryRef.current = setTimeout(poll, 2000 * 2 ** (attempt - 1));
          }
        })
        .catch(() => {
          if (attempt < maxRetries) {
            attempt++;
            graphRetryRef.current = setTimeout(poll, 2000 * 2 ** (attempt - 1));
          } else {
            setGraphData(null);
          }
        });
    };
    graphRetryRef.current = setTimeout(poll, 3000);
  }, [threadId]);

  const handleNamingComplete = useCallback(() => {
    refreshThreads();
    setNamingTask(undefined);
  }, [refreshThreads]);

  const hasAiContent = messages.some(
    (m) => m.type === "ai" && getContentString(m.content).trim().length > 0,
  );

  // Trigger thread name generation as soon as first AI output arrives (only for new conversations)
  useEffect(() => {
    if (
      !isNewConversationRef.current ||
      nameGenerationTriggeredRef.current ||
      !hasAiContent
    )
      return;

    const firstHuman = messages.find((m) => m.type === "human");
    const firstAi = messages.find(
      (m) => m.type === "ai" && getContentString(m.content).trim().length > 0,
    );

    if (firstHuman && firstAi) {
      const userMessage = getContentString(firstHuman.content);
      const assistantMessage = getContentString(firstAi.content);

      if (userMessage && assistantMessage) {
        nameGenerationTriggeredRef.current = true;
        triggerThreadNameGeneration(threadId, userMessage, assistantMessage)
          .then((result) => {
            setNamingTask(result);
          })
          .catch((err) =>
            console.error("Failed to trigger thread name generation:", err),
          );
      }
    }
  }, [messages, hasAiContent, threadId]);

  useEffect(() => {
    if (sentInitialRef.current || stream.isThreadLoading) return;
    const stored = sessionStorage.getItem("initial_message");
    if (!stored) return;

    sentInitialRef.current = true;
    isNewConversationRef.current = true;
    sessionStorage.removeItem("initial_message");

    const humanMessage: Message = {
      id: uuidv4(),
      type: "human",
      content: [{ type: "text", text: stored }],
    };

    setDismissedError(false);
    stream.submit(
      { messages: [humanMessage] },
      {
        optimisticValues: (prev) => ({
          ...prev,
          messages: [...(prev.messages ?? []), humanMessage],
        }),
        onGraphReady: fetchGraph,
        onGraphFailed: fetchGraphWithRetry,
      },
    );
  }, [stream]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  useEffect(() => {
    fetchGraph();
    return () => {
      if (graphRetryRef.current) clearTimeout(graphRetryRef.current);
    };
  }, [fetchGraph]);

  // Reset error dismissal when a new error comes in
  useEffect(() => {
    if (error) setDismissedError(false);
  }, [error]);

  // Show loading toast while sentinel runs in parallel with the agent
  useEffect(() => {
    if (isLoading) {
      toast.loading("[BACKGROUND] Anomaly scanning", {
        id: "sentinel-scanning",
      });
    } else {
      toast.dismiss("sentinel-scanning");
    }
  }, [isLoading]);

  // Persistent sentinel alert toasts (tier >= 1)
  useEffect(() => {
    const s = stream.sentinelResult;
    if (!s || s.tier < 1) return;
    const title = s.tier >= 3 ? "Attack Path Detected" : "Anomaly Detected";
    const fn = s.tier >= 3 ? toast.error : toast.warning;
    fn(title, {
      description: s.summary,
      duration: Number.POSITIVE_INFINITY,
    });
  }, [stream.sentinelResult]);

  if (error && !isThreadLoading && messages.length === 0) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4 text-center px-8">
          <XCircle className="h-10 w-10 text-destructive/60" />
          <p className="text-base text-muted-foreground">
            Failed to load this thread. It may have been deleted or is
            unavailable.
          </p>
        </div>
      </div>
    );
  }

  if (isThreadLoading && messages.length === 0) {
    return (
      <div className="flex min-h-0 flex-1 flex-col bg-background">
        <div className="flex flex-1 items-center justify-center">
          <MyLoader />
        </div>
      </div>
    );
  }

  const showError = error && !isLoading && !dismissedError;

  return (
    <div className="flex min-h-0 flex-1 bg-background">
      {namingTask && (
        <NamingTaskSubscriber
          runId={namingTask.runId}
          accessToken={namingTask.publicAccessToken}
          onComplete={handleNamingComplete}
        />
      )}

      <div className="flex w-1/2 flex-col border-r">
        <div
          ref={scrollRef}
          className="min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-8"
        >
          <div className="flex flex-col gap-6 py-14">
            <MessageList messages={messages} isLoading={isLoading} />
          </div>
        </div>
        {showError ? (
          <StreamErrorBanner
            error={error}
            onDismiss={() => setDismissedError(true)}
          />
        ) : null}
        <div className="shrink-0 bg-background px-6 py-5 pt-0">
          <ChatComposer
            stream={stream}
            onFirstTokenReset={() => setDismissedError(false)}
            onGraphReady={fetchGraph}
            onGraphFailed={fetchGraphWithRetry}
          />
        </div>
      </div>

      <div className="w-1/2">
        <NvlGraph
          nodes={graphData?.nodes ?? []}
          rels={graphData?.edges ?? []}
          threadId={threadId}
          onGraphUpdate={fetchGraph}
        />
      </div>
    </div>
  );
}
