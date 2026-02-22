"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { createThread } from "@/actions/thread";
import { Composer, ComposerProvider } from "./index";

export function NewThreadComposer() {
  const router = useRouter();
  const [input, setInput] = useState("");
  const [isPending, startTransition] = useTransition();
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = async () => {
    if (!input.trim() || isPending) return;
    const threadId = await createThread();
    localStorage.setItem("threadId", threadId.threadId);
    sessionStorage.setItem("initial_message", input.trim());
    router.push(`/threads/${threadId.threadId}`);
  };

  return (
    <ComposerProvider
      state={{ input, isLoading: isPending }}
      actions={{ setInput, submit: handleSubmit }}
      meta={{
        inputRef,
        placeholder: "Type your message...",
        loadingLabel: "Creating...",
      }}
    >
      <Composer.Frame>
        <Composer.Input className="w-full min-h-24 resize-none rounded pr-16 pb-16 p-4" />
        <div className="absolute bottom-4 right-4">
          <Composer.ActionButton />
        </div>
      </Composer.Frame>
    </ComposerProvider>
  );
}
