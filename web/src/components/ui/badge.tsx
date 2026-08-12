import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * The status variants read the reserved `ok` / `warn` / `bad` tokens, which are
 * never used for a data series. That is what lets a colour mean one thing across
 * the whole console: green here and green in a chart legend would be two
 * different claims wearing the same paint.
 *
 * Every status badge also carries a dot and a label, so the state survives being
 * read by someone who cannot distinguish the hues.
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/10 text-primary",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-foreground",
        ok: "border-ok/25 bg-ok/10 text-ok",
        warn: "border-warn/25 bg-warn/10 text-warn",
        bad: "border-bad/25 bg-bad/10 text-bad",
        muted: "border-transparent bg-muted text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  dot?: boolean;
}

export function Badge({ className, variant, dot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot ? <span className="size-1.5 rounded-full bg-current" aria-hidden /> : null}
      {children}
    </span>
  );
}

export { badgeVariants };
