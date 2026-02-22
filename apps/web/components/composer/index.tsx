"use client";

export {
  ComposerActionButton,
  ComposerFooter,
  ComposerFrame,
  ComposerInput,
  ComposerLoadingButton,
  ComposerStopButton,
  ComposerSubmitButton,
} from "./components";
export type {
  ComposerActions,
  ComposerContextValue,
  ComposerMeta,
  ComposerProviderProps,
  ComposerState,
} from "./context";
export { ComposerContext, ComposerProvider, useComposer } from "./context";

import {
  ComposerActionButton,
  ComposerFooter,
  ComposerFrame,
  ComposerInput,
  ComposerLoadingButton,
  ComposerStopButton,
  ComposerSubmitButton,
} from "./components";
// Compound component namespace
import { ComposerProvider } from "./context";

export const Composer = {
  Provider: ComposerProvider,
  Frame: ComposerFrame,
  Input: ComposerInput,
  Footer: ComposerFooter,
  SubmitButton: ComposerSubmitButton,
  StopButton: ComposerStopButton,
  LoadingButton: ComposerLoadingButton,
  ActionButton: ComposerActionButton,
};
