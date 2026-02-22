"use client";

import { CircleStop, Forward, Send } from "lucide-react";
import type { FormEvent, KeyboardEvent, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { MyLoader } from "../ui/my-loader";
import { useComposer } from "./context";

export function ComposerFrame({ children }: { children: ReactNode }) {
  const { actions } = useComposer();

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    actions.submit();
  };

  return (
    <form
      onSubmit={handleSubmit}
      className={cn(
        "w-full min-w-0 max-w-full rounded-xl border border-border bg-background overflow-hidden",
      )}
    >
      {children}
    </form>
  );
}

export function ComposerInput({ className }: { className?: string }) {
  const { state, actions, meta } = useComposer();

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      e.key === "Enter" &&
      !e.shiftKey &&
      !e.metaKey &&
      !e.nativeEvent.isComposing
    ) {
      e.preventDefault();
      actions.submit();
    }
  };

  return (
    <Textarea
      ref={meta.inputRef}
      value={state.input}
      onChange={(e) => actions.setInput(e.target.value)}
      onKeyDown={handleKeyDown}
      placeholder={meta.placeholder ?? "Type your message..."}
      className={className}
      style={{ fieldSizing: "fixed" } as React.CSSProperties}
    />
  );
}

export function ComposerFooter({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-row items-center justify-end border-t border-border bg-muted/30 px-3 py-2.5">
      {children}
    </div>
  );
}

export function ComposerSubmitButton() {
  const { state } = useComposer();

  return (
    <Button
      type="submit"
      variant="outline"
      size="sm"
      disabled={!state.input.trim()}
      aria-label="Send"
    >
      <Forward className="size-4" />
      Send
    </Button>
  );
}

export function ComposerStopButton() {
  const { actions } = useComposer();

  if (!actions.stop) return null;

  return (
    <Button
      type="button"
      size="sm"
      variant="destructive"
      onClick={actions.stop}
    >
      <CircleStop className="h-5 w-5" />
      Stop
    </Button>
  );
}

export function ComposerLoadingButton() {
  const { meta } = useComposer();

  return (
    <Button type="button" size="sm" disabled>
      <MyLoader />
      {meta.loadingLabel ?? "Loading"}
    </Button>
  );
}

export function ComposerActionButton() {
  const { state, actions } = useComposer();

  if (state.isLoading && actions.stop) {
    return <ComposerStopButton />;
  }

  if (state.isLoading) {
    return <ComposerLoadingButton />;
  }

  return <ComposerSubmitButton />;
}
