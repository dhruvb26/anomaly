"use server";

import { auth, tasks } from "@trigger.dev/sdk/v3";
import type { generateToolDescriptionTask } from "@/trigger/generate-tool-description";

export async function triggerToolDescriptionGeneration(toolName: string) {
  const handle = await tasks.trigger<typeof generateToolDescriptionTask>(
    "generate-tool-description",
    { toolName },
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

export async function triggerToolDescriptionGenerationBatch(
  toolNames: string[],
) {
  const uniqueNames = [...new Set(toolNames)];

  const results = await Promise.all(
    uniqueNames.map(async (toolName) => {
      const handle = await tasks.trigger<typeof generateToolDescriptionTask>(
        "generate-tool-description",
        { toolName },
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
        toolName,
        runId: handle.id,
        publicAccessToken,
      };
    }),
  );

  return results;
}
