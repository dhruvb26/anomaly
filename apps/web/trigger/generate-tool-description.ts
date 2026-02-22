import { ChatAnthropic } from "@langchain/anthropic";
import { logger, task } from "@trigger.dev/sdk/v3";
import { mkdir, readFile, writeFile } from "fs/promises";
import { join } from "path";
import { z } from "zod";

const CACHE_DIR = join(process.cwd(), ".cache");
const CACHE_FILE = join(CACHE_DIR, "tool-descriptions.json");

const ToolDescriptionSchema = z.object({
  description: z
    .string()
    .describe(
      "A short, human-friendly description of what this tool does. Should be 2-4 words in present continuous tense (e.g., 'Fetching Emails', 'Searching Documents'). No quotes or punctuation at the end.",
    ),
});

type ToolDescriptionCache = Record<string, string>;

async function readCache(): Promise<ToolDescriptionCache> {
  try {
    const data = await readFile(CACHE_FILE, "utf-8");
    return JSON.parse(data) as ToolDescriptionCache;
  } catch {
    return {};
  }
}

async function writeCache(cache: ToolDescriptionCache): Promise<void> {
  await mkdir(CACHE_DIR, { recursive: true });
  await writeFile(CACHE_FILE, JSON.stringify(cache, null, 2), "utf-8");
}

export const generateToolDescriptionTask = task({
  id: "generate-tool-description",
  maxDuration: 30,
  run: async (payload: { toolName: string }) => {
    const { toolName } = payload;

    // Check cache first
    const cache = await readCache();
    if (cache[toolName]) {
      logger.info("Tool description found in cache", {
        toolName,
        description: cache[toolName],
      });
      return { toolName, description: cache[toolName], cached: true };
    }

    // Generate new description
    const model = new ChatAnthropic({
      model: "claude-haiku-4-5-20251001",
      temperature: 0.7,
    }).withStructuredOutput(ToolDescriptionSchema);

    const prompt = `Convert this tool name into a short, human-friendly description.

Tool name: "${toolName}"

Examples:
- "GMAIL_FETCH_EMAIL" → "Fetching Emails"
- "COMPOSIO_SEARCH" → "Searching"
- "SLACK_SEND_MESSAGE" → "Sending Message"
- "GITHUB_CREATE_ISSUE" → "Creating Issue"
- "GOOGLE_CALENDAR_LIST_EVENTS" → "Listing Events"

Generate a 2-4 word description in present continuous tense that describes what the tool is doing.`;

    const response = await model.invoke(prompt);
    const description = response.description.trim();

    // Save to cache
    cache[toolName] = description;
    await writeCache(cache);

    logger.info("Generated and cached tool description", {
      toolName,
      description,
    });

    return { toolName, description, cached: false };
  },
});
