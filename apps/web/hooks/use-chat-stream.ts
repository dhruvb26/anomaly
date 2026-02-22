"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { useCallback, useEffect, useRef, useState } from "react";
import { env } from "@/env";

const API_URL = env.NEXT_PUBLIC_LANGSMITH_API_URL;

export type ChatState = { messages: Message[] };

export type SentinelResult = {
  tier: number;
  summary: string;
  recommendations: string[];
};

export type ChatStream = {
  messages: Message[];
  isLoading: boolean;
  isThreadLoading: boolean;
  error: unknown;
  sentinelResult: SentinelResult | null;
  submit: (
    state: { messages: Message[] },
    options?: {
      optimisticValues?: (prev: ChatState) => ChatState;
      onGraphReady?: () => void;
      onGraphFailed?: () => void;
    },
  ) => void;
  stop: () => void;
};

export function useChatStream(threadId: string | null): ChatStream {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isThreadLoading, setIsThreadLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [sentinelResult, setSentinelResult] = useState<SentinelResult | null>(
    null,
  );
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!threadId) {
      setIsThreadLoading(false);
      return;
    }

    let cancelled = false;
    setIsThreadLoading(true);
    setError(null);

    fetch(`${API_URL}/threads/${threadId}/state`)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load thread: ${res.status}`);
        return res.json();
      })
      .then((data: { messages?: Message[] }) => {
        if (!cancelled) setMessages(data.messages ?? []);
        if (!cancelled) setIsThreadLoading(false);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err);
          setIsThreadLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [threadId]);

  const submit = useCallback(
    (
      state: { messages: Message[] },
      options?: {
        optimisticValues?: (prev: ChatState) => ChatState;
        onGraphReady?: () => void;
        onGraphFailed?: () => void;
      },
    ) => {
      if (!threadId) return;

      if (options?.optimisticValues) {
        setMessages((prev) => {
          const result = options.optimisticValues!({ messages: prev });
          return result.messages;
        });
      }

      setIsLoading(true);
      setError(null);

      const abort = new AbortController();
      abortRef.current = abort;

      fetch(`${API_URL}/threads/${threadId}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: state.messages }),
        signal: abort.signal,
      })
        .then(async (response) => {
          if (!response.ok) {
            const body = await response.text().catch(() => "");
            throw new Error(body || `Request failed: ${response.status}`);
          }
          return response.json() as Promise<{
            messages: Message[];
            graph_ready: boolean;
            sentinel: SentinelResult | null;
          }>;
        })
        .then((data) => {
          setMessages(data.messages);
          setIsLoading(false);
          setSentinelResult(data.sentinel ?? null);

          if (data.graph_ready) {
            options?.onGraphReady?.();
          } else {
            options?.onGraphFailed?.();
          }
        })
        .catch((err) => {
          if (err instanceof DOMException && err.name === "AbortError") {
            setIsLoading(false);
            return;
          }
          setError(err);
          setIsLoading(false);
        });
    },
    [threadId],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsLoading(false);
  }, []);

  return {
    messages,
    isLoading,
    isThreadLoading,
    error,
    sentinelResult,
    submit,
    stop,
  };
}
