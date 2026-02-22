"use client";

import { createContext, type ReactNode, type RefObject, use } from "react";

export interface ComposerState {
  input: string;
  isLoading: boolean;
}

export interface ComposerActions {
  setInput: (value: string) => void;
  submit: () => void;
  stop?: () => void;
}

export interface ComposerMeta {
  inputRef?: RefObject<HTMLTextAreaElement | null>;
  placeholder?: string;
  submitLabel?: string;
  loadingLabel?: string;
}

export interface ComposerContextValue {
  state: ComposerState;
  actions: ComposerActions;
  meta: ComposerMeta;
}

export const ComposerContext = createContext<ComposerContextValue | null>(null);

export function useComposer(): ComposerContextValue {
  const context = use(ComposerContext);
  if (!context) {
    throw new Error("useComposer must be used within a ComposerProvider");
  }
  return context;
}

export interface ComposerProviderProps {
  children: ReactNode;
  state: ComposerState;
  actions: ComposerActions;
  meta?: ComposerMeta;
}

export function ComposerProvider({
  children,
  state,
  actions,
  meta = {},
}: ComposerProviderProps) {
  return (
    <ComposerContext value={{ state, actions, meta }}>
      {children}
    </ComposerContext>
  );
}
