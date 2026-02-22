"use client";

import { Bug, Delete, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type * as React from "react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useThreadRefresh } from "@/contexts/sidebar-context";
import { env } from "@/env";

interface Thread {
  thread_id: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

const API_URL = env.NEXT_PUBLIC_LANGSMITH_API_URL;

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname();
  const router = useRouter();
  const [threads, setThreads] = useState<Thread[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const { registerRefresh } = useThreadRefresh();

  const handleDelete = useCallback(
    async (e: React.MouseEvent, threadId: string) => {
      e.preventDefault();
      e.stopPropagation();
      if (deletingId) return;
      setDeletingId(threadId);
      try {
        await fetch(`${API_URL}/threads/${threadId}`, { method: "DELETE" });
        setThreads((prev) => prev.filter((t) => t.thread_id !== threadId));
        if (pathname === `/threads/${threadId}`) {
          router.push("/");
        }
      } catch (err) {
        console.error("Failed to delete thread:", err);
      } finally {
        setDeletingId(null);
      }
    },
    [deletingId, pathname, router],
  );

  const fetchThreads = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/threads?limit=50`);
      if (!res.ok) throw new Error(`Failed to fetch threads: ${res.status}`);
      const result: Thread[] = await res.json();
      setThreads(result);
    } catch (err) {
      console.error("Failed to fetch threads:", err);
    }
  }, []);

  useEffect(() => {
    registerRefresh(fetchThreads);
  }, [registerRefresh, fetchThreads]);

  useEffect(() => {
    fetchThreads();
  }, [fetchThreads, pathname]);

  return (
    <Sidebar {...props}>
      <SidebarHeader className="p-5">
        <Link href="/" className="flex items-end gap-3">
          <Bug
            className="w-9 h-9 bg-sidebar-primary p-2 rounded-md"
            strokeWidth={1.9}
            color="white"
          />
          <h1 className="text-2xl font-medium">Anomaly</h1>
        </Link>
      </SidebarHeader>
      <SidebarContent className="p-3">
        <SidebarGroup>
          <SidebarGroupLabel className="text-base px-0 font-medium">
            Threads
          </SidebarGroupLabel>
          {threads.length > 0 ? (
            <SidebarGroupContent>
              <SidebarMenu>
                {threads.map((thread) => {
                  const threadUrl = `/threads/${thread.thread_id}`;
                  const isActive = pathname === threadUrl;
                  const name = (thread.metadata as { name?: string })?.name;
                  const isDeleting = deletingId === thread.thread_id;
                  return (
                    <SidebarMenuItem
                      key={thread.thread_id}
                      className="group/item"
                    >
                      <SidebarMenuButton
                        size="sm"
                        asChild
                        isActive={isActive}
                        className="pr-7 group-hover/item:bg-sidebar-accent group-hover/item:text-sidebar-accent-foreground"
                      >
                        <Link href={threadUrl}>
                          {name ? (
                            <span
                              className="truncate text-muted-foreground"
                              title={name}
                            >
                              {name}
                            </span>
                          ) : (
                            <span className="inline-block h-4 w-24 rounded bg-muted animate-pulse" />
                          )}
                        </Link>
                      </SidebarMenuButton>
                      <button
                        onClick={(e) => handleDelete(e, thread.thread_id)}
                        disabled={isDeleting}
                        className="absolute right-1 top-1/2 -translate-y-1/2 flex h-6 w-6 items-center justify-center rounded opacity-0 group-hover/item:opacity-100 text-muted-foreground hover:text-foreground transition-opacity disabled:cursor-not-allowed"
                        aria-label="Delete thread"
                      >
                        <Delete className="h-5 w-5" />
                      </button>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          ) : null}
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="p-5">
        <Button
          className="w-full group"
          variant="outline"
          onClick={() => router.push("/threads/new")}
        >
          <Plus className="h-4 w-4 shrink-0" />
          <span>New Thread</span>
        </Button>
        <Button className="w-full group" variant="default">
          <span>Run Baselines</span>
        </Button>
      </SidebarFooter>
    </Sidebar>
  );
}
