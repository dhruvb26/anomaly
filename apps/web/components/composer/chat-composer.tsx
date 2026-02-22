"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { Check, ClipboardCopy } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ChatStream } from "@/hooks/use-chat-stream";
import { Composer, ComposerProvider } from "./index";

interface ChatComposerProps {
  stream: ChatStream;
  onFirstTokenReset?: () => void;
  onGraphReady?: () => void;
  onGraphFailed?: () => void;
}

export function ChatComposer({
  stream,
  onFirstTokenReset,
  onGraphReady,
  onGraphFailed,
}: ChatComposerProps) {
  const [input, setInput] = useState("");
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = () => {
    if (!input.trim() || stream.isLoading) return;

    const humanMessage: Message = {
      id: uuidv4(),
      type: "human",
      content: [{ type: "text", text: input }],
    };

    onFirstTokenReset?.();
    stream.submit(
      { messages: [humanMessage] },
      {
        optimisticValues: (prev) => ({
          ...prev,
          messages: [...(prev.messages ?? []), humanMessage],
        }),
        onGraphReady,
        onGraphFailed,
      },
    );

    setInput("");
  };

  const handleCopy = useCallback(() => {
    const json = JSON.stringify(stream.messages, null, 2);
    navigator.clipboard.writeText(json).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [stream.messages]);

  return (
    <ComposerProvider
      state={{ input, isLoading: stream.isLoading }}
      actions={{
        setInput,
        submit: handleSubmit,
        stop: stream.stop,
      }}
      meta={{
        inputRef,
        placeholder: "What would you like to know?",
      }}
    >
      <Composer.Frame>
        <Composer.Input className="w-full min-w-0 max-w-full min-h-20 resize-none border-0 bg-transparent px-4 pt-3 pb-3 text-base placeholder:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0" />
        <Composer.Footer>
          <div className="flex w-full items-center justify-between">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={handleCopy}
              disabled={stream.messages.length === 0}
              className="text-muted-foreground"
            >
              {copied ? (
                <>
                  <Check className="size-4" /> Copied
                </>
              ) : (
                <>
                  <ClipboardCopy className="size-4" /> Copy Conversation
                </>
              )}
            </Button>

            <Composer.ActionButton />
          </div>
        </Composer.Footer>
      </Composer.Frame>
    </ComposerProvider>
  );
}
