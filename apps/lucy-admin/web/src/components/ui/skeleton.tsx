import * as React from "react";
import { cn } from "@/lib/utils";

/** Fixed-size placeholder that reserves layout while data loads (no CLS). */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("ui-skeleton", className)}
      {...props}
    />
  );
}
