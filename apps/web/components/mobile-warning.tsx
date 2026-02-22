"use client";

import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

export function MobileWarning() {
  const isMobile = useIsMobile();

  if (!isMobile) return null;

  return (
    <div
      role="alert"
      className={cn(
        "fixed inset-0 z-100 flex items-center justify-center p-6",
        "bg-background/80 backdrop-blur-md",
      )}
    >
      <p
        className={cn(
          "max-w-sm text-center text-base font-medium text-foreground",
          "rounded-lg bg-card/90 px-6 py-5 shadow-lg ring-1 ring-border",
        )}
      >
        This app is best experienced on a larger screen. Please use a desktop or
        tablet.
      </p>
    </div>
  );
}
