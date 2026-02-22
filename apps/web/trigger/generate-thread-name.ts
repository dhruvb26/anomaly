import { ChatAnthropic } from "@langchain/anthropic";
import { logger, task } from "@trigger.dev/sdk/v3";
import { z } from "zod";

const ThreadNameSchema = z.object({
  name: z
    .string()
    .describe(
      "A short, creative, and memorable name for the conversation thread. Should be at least 3-4 words, capture the essence of what's being discussed, and be slightly playful or interesting. No quotes or punctuation.",
    ),
});

export const generateThreadNameTask = task({
  id: "generate-thread-name",
  maxDuration: 60,
  run: async (payload: {
    threadId: string;
    userMessage: string;
    assistantMessage: string;
    apiUrl: string;
  }) => {
    const { threadId, userMessage, assistantMessage, apiUrl } = payload;

    const model = new ChatAnthropic({
      model: "claude-haiku-4-5-20251001",
      temperature: 1.0,
    }).withStructuredOutput(ThreadNameSchema);

    const prompt = `Generate a thread name based on this conversation:

    User's message: "${userMessage.slice(0, 500)}"

    Assistant's response: "${assistantMessage.slice(0, 500)}"`;

    const response = await model.invoke(prompt);
    const threadName = response.name.trim().slice(0, 60);

    const patchUrl = `${apiUrl}/threads/${threadId}`;
    const patchResponse = await fetch(patchUrl, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        metadata: {
          name: threadName,
          namedAt: new Date().toISOString(),
        },
      }),
    });

    if (!patchResponse.ok) {
      const errorText = await patchResponse.text();
      logger.error("Failed to update thread metadata", {
        threadId,
        status: patchResponse.status,
        error: errorText,
      });
      throw new Error(
        `Failed to update thread: ${patchResponse.status} ${errorText}`,
      );
    }

    return { threadId, threadName };
  },
});
