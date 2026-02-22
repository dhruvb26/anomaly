"use server";

import { auth, tasks } from "@trigger.dev/sdk/v3";
import { env } from "@/env";
import type { generateThreadNameTask } from "@/trigger/generate-thread-name";

export async function triggerThreadNameGeneration(
  threadId: string,
  userMessage: string,
  assistantMessage: string,
) {
  const handle = await tasks.trigger<typeof generateThreadNameTask>(
    "generate-thread-name",
    {
      threadId,
      userMessage,
      assistantMessage,
      apiUrl: env.LANGSMITH_API_URL,
    },
  );

  const publicAccessToken = await auth.createPublicToken({
    scopes: {
      read: {
        runs: [handle.id],
      },
    },
    expirationTime: "1h",
  });

  return {
    runId: handle.id,
    publicAccessToken,
  };
}
