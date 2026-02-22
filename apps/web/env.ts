import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

export const env = createEnv({
  server: {
    OPENAI_API_KEY: z.string().min(1),
    ANTHROPIC_API_KEY: z.string().min(1),
    LANGSMITH_API_KEY: z.string().min(1),
    LANGSMITH_TRACING: z.string().optional(),
    LANGSMITH_WORKSPACE_ID: z.string().min(1),
    LANGSMITH_PROJECT: z.string().min(1),
    POSTGRES_URL: z.string().min(1),
    COMPOSIO_API_KEY: z.string().min(1),
    LANGSMITH_API_URL: z.string().min(1),
    TRIGGER_SECRET_KEY: z.string().min(1),
  },
  client: {
    NEXT_PUBLIC_LANGSMITH_API_URL: z.string().min(1),
  },
  runtimeEnv: {
    OPENAI_API_KEY: process.env.OPENAI_API_KEY,
    ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY,
    LANGSMITH_API_KEY: process.env.LANGSMITH_API_KEY,
    LANGSMITH_TRACING: process.env.LANGSMITH_TRACING,
    LANGSMITH_WORKSPACE_ID: process.env.LANGSMITH_WORKSPACE_ID,
    LANGSMITH_PROJECT: process.env.LANGSMITH_PROJECT,
    POSTGRES_URL: process.env.POSTGRES_URL,
    COMPOSIO_API_KEY: process.env.COMPOSIO_API_KEY,
    LANGSMITH_API_URL: process.env.LANGSMITH_API_URL,
    NEXT_PUBLIC_LANGSMITH_API_URL: process.env.NEXT_PUBLIC_LANGSMITH_API_URL,
    TRIGGER_SECRET_KEY: process.env.TRIGGER_SECRET_KEY,
  },
});
