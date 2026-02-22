"use server";

import { env } from "@/env";

export async function createThread(): Promise<{ threadId: string }> {
  const res = await fetch(`${env.LANGSMITH_API_URL}/threads`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to create thread: ${res.status}`);
  const data = (await res.json()) as { thread_id: string };
  return { threadId: data.thread_id };
}
