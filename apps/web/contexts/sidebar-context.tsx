"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useRef,
} from "react";

interface ThreadRefreshContextType {
  refreshThreads: () => void;
  registerRefresh: (callback: () => void) => void;
}

const ThreadRefreshContext = createContext<ThreadRefreshContextType | null>(
  null,
);

export function ThreadRefreshProvider({ children }: { children: ReactNode }) {
  const refreshCallbackRef = useRef<(() => void) | null>(null);

  const registerRefresh = useCallback((callback: () => void) => {
    refreshCallbackRef.current = callback;
  }, []);

  const refreshThreads = useCallback(() => {
    refreshCallbackRef.current?.();
  }, []);

  return (
    <ThreadRefreshContext.Provider value={{ refreshThreads, registerRefresh }}>
      {children}
    </ThreadRefreshContext.Provider>
  );
}

export function useThreadRefresh() {
  const context = useContext(ThreadRefreshContext);
  if (!context) {
    throw new Error(
      "useThreadRefresh must be used within a ThreadRefreshProvider",
    );
  }
  return context;
}
