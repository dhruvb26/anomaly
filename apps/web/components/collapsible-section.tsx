"use client";

import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

interface CollapsibleSectionProps {
  label: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}

export function CollapsibleSection({
  label,
  children,
  defaultOpen = false,
  className,
}: CollapsibleSectionProps) {
  return (
    <Collapsible
      defaultOpen={defaultOpen}
      className={cn("flex flex-col", className)}
    >
      <CollapsibleTrigger
        className={cn(
          "flex items-center gap-2.5 text-base text-muted-foreground hover:text-foreground transition-colors",
          "px-0 text-left [&[data-state=open]>svg:first-child]:rotate-90",
        )}
      >
        <ChevronRight className="size-5 transition-transform" />
        {label}
      </CollapsibleTrigger>
      <CollapsibleContent className="pl-7 pt-2.5">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}
