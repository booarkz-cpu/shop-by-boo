import * as React from "react";
import { cn } from "@/lib/utils";

export type Tone = "ok" | "warn" | "danger" | "idle" | "info";

export function StatusDot({
  tone,
  pulse = false,
  className,
}: {
  tone: Tone;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      data-tone={tone}
      data-pulse={pulse || undefined}
      className={cn("ui-dot", className)}
    />
  );
}

export function StatusBadge({
  tone,
  children,
  className,
}: {
  tone: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span data-tone={tone} className={cn("ui-badge", className)}>
      <StatusDot tone={tone} />
      {children}
    </span>
  );
}
