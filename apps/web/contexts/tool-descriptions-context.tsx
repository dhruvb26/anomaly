"use client";

import { useRealtimeRun } from "@trigger.dev/react-hooks";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { triggerToolDescriptionGeneration } from "@/actions/generate-tool-description";
import type { generateToolDescriptionTask } from "@/trigger/generate-tool-description";

const STORAGE_KEY = "tool-descriptions-cache";

type DescriptionCache = Record<string, string>;
type PendingTask = { runId: string; accessToken: string };

interface ToolDescriptionsContextValue {
  getDescription: (toolName: string) => string | undefined;
  requestDescription: (toolName: string) => void;
  isLoading: (toolName: string) => boolean;
}

const ToolDescriptionsContext =
  createContext<ToolDescriptionsContextValue | null>(null);

function getLocalCache(): DescriptionCache {
  if (typeof window === "undefined") return {};
  try {
    const data = localStorage.getItem(STORAGE_KEY);
    return data ? (JSON.parse(data) as DescriptionCache) : {};
  } catch {
    return {};
  }
}

function setLocalCache(cache: DescriptionCache): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
}

/** Subscribes to a single tool description task */
function TaskSubscriber({
  toolName,
  runId,
  accessToken,
  onComplete,
}: {
  toolName: string;
  runId: string;
  accessToken: string;
  onComplete: (toolName: string, description: string) => void;
}) {
  const { run } = useRealtimeRun<typeof generateToolDescriptionTask>(runId, {
    accessToken,
  });

  useEffect(() => {
    if (run?.status === "COMPLETED" && run.output?.description) {
      onComplete(toolName, run.output.description);
    }
  }, [run?.status, run?.output, toolName, onComplete]);

  return null;
}

export function ToolDescriptionsProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [descriptions, setDescriptions] = useState<DescriptionCache>({});
  const [pendingTasks, setPendingTasks] = useState<Map<string, PendingTask>>(
    new Map(),
  );
  const [requestedTools, setRequestedTools] = useState<Set<string>>(new Set());

  // Load from localStorage on mount
  useEffect(() => {
    setDescriptions(getLocalCache());
  }, []);

  const handleComplete = useCallback(
    (toolName: string, description: string) => {
      setDescriptions((prev) => {
        const updated = { ...prev, [toolName]: description };
        setLocalCache(updated);
        return updated;
      });
      setPendingTasks((prev) => {
        const updated = new Map(prev);
        updated.delete(toolName);
        return updated;
      });
    },
    [],
  );

  const requestDescription = useCallback(
    (toolName: string) => {
      // Skip if already have description or already requested
      if (descriptions[toolName] || requestedTools.has(toolName)) {
        return;
      }

      setRequestedTools((prev) => new Set(prev).add(toolName));

      triggerToolDescriptionGeneration(toolName)
        .then((result) => {
          setPendingTasks((prev) => {
            const updated = new Map(prev);
            updated.set(toolName, {
              runId: result.runId,
              accessToken: result.publicAccessToken,
            });
            return updated;
          });
        })
        .catch((error) => {
          console.error(
            "Failed to trigger tool description generation:",
            error,
          );
          setRequestedTools((prev) => {
            const updated = new Set(prev);
            updated.delete(toolName);
            return updated;
          });
        });
    },
    [descriptions, requestedTools],
  );

  const getDescription = useCallback(
    (toolName: string): string | undefined => {
      return descriptions[toolName];
    },
    [descriptions],
  );

  const isLoading = useCallback(
    (toolName: string): boolean => {
      // Loading if requested but no description yet
      return requestedTools.has(toolName) && !descriptions[toolName];
    },
    [requestedTools, descriptions],
  );

  return (
    <ToolDescriptionsContext.Provider
      value={{ getDescription, requestDescription, isLoading }}
    >
      {children}
      {Array.from(pendingTasks.entries()).map(([toolName, task]) => (
        <TaskSubscriber
          key={task.runId}
          toolName={toolName}
          runId={task.runId}
          accessToken={task.accessToken}
          onComplete={handleComplete}
        />
      ))}
    </ToolDescriptionsContext.Provider>
  );
}

export function useToolDescriptions() {
  const context = useContext(ToolDescriptionsContext);
  if (!context) {
    throw new Error(
      "useToolDescriptions must be used within ToolDescriptionsProvider",
    );
  }
  return context;
}
