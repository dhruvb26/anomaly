import { CollapsibleSection } from "@/components/collapsible-section";

interface ExtendedThinkingBlockProps {
  thoughts: string[];
}

export function ExtendedThinkingBlock({
  thoughts,
}: ExtendedThinkingBlockProps) {
  if (thoughts.length === 0) return null;

  return (
    <CollapsibleSection label="Extended Thinking">
      <p className="whitespace-pre-wrap text-base leading-relaxed text-muted-foreground/70">
        {thoughts.join("\n\n")}
      </p>
    </CollapsibleSection>
  );
}
