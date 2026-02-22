"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";
import { createThread } from "@/actions/thread";
import { Composer, ComposerProvider } from "@/components/composer/index";

export default function NewThreadPage() {
  const router = useRouter();
  const [input, setInput] = useState("");
  const [isPending, startTransition] = useTransition();
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = () => {
    if (!input.trim() || isPending) return;
    const message = input.trim();
    setInput("");

    startTransition(async () => {
      const { threadId } = await createThread();
      sessionStorage.setItem("initial_message", message);
      router.push(`/threads/${threadId}`);
    });
  };

  return (
    <div className="flex min-h-0 flex-1 bg-background">
      <div className="flex w-1/2 flex-col border-r">
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-8" />
        <div className="shrink-0 bg-background px-6 py-5 pt-0">
          <ComposerProvider
            state={{ input, isLoading: isPending }}
            actions={{ setInput, submit: handleSubmit }}
            meta={{
              inputRef,
              placeholder: "What would you like to know?",
            }}
          >
            <Composer.Frame>
              <Composer.Input className="w-full min-w-0 max-w-full min-h-20 resize-none border-0 bg-transparent px-4 pt-3 pb-3 text-base placeholder:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0" />
              <Composer.Footer>
                <Composer.ActionButton />
              </Composer.Footer>
            </Composer.Frame>
          </ComposerProvider>
        </div>
      </div>
      <div className="w-1/2" />
    </div>
  );
}
