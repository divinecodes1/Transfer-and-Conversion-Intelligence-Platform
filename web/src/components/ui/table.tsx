import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Every chart in this console ships with a table beside it, so no value is
 * reachable only by hovering. That rule is why this primitive exists at all.
 *
 * Geometry follows the portal spec: a 44px header, rows in the 48-56 band, and
 * horizontal rules only, with no zebra striping. Vertical borders and
 * alternating fills both add ink that carries no information — on a register of
 * two hundred transfers they turn a scan into a search.
 *
 * Body text is `text-sm`, which the scale in styles.css sets to 15px. It was
 * 14px, and a register that is read down a column all day is the last place to
 * economise on x-height.
 */
export const Table = React.forwardRef<
  HTMLTableElement,
  React.HTMLAttributes<HTMLTableElement> & {
    /**
     * Cap the body height so the header can pin while the rows scroll.
     *
     * Off by default, and that is deliberate: the wrapper below sets
     * `overflow-x-auto`, and CSS computes `overflow-y` to `auto` alongside it —
     * so the wrapper is always a scroll container. Without a height limit it
     * never actually scrolls, and a sticky header inside it silently does
     * nothing. Passing a height is what makes the stickiness real.
     */
    maxHeight?: string;
  }
>(({ className, maxHeight, ...props }, ref) => (
  <div
    className={cn("relative w-full overflow-auto", maxHeight)}
    // A tall scrollable region is a focus target for keyboard users, who
    // otherwise cannot reach rows below the fold without a mouse.
    tabIndex={maxHeight ? 0 : undefined}
  >
    <table ref={ref} className={cn("w-full caption-bottom text-sm", className)} {...props} />
  </div>
));
Table.displayName = "Table";

export const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("[&_tr]:border-b [&_tr]:border-border", className)} {...props} />
));
TableHeader.displayName = "TableHeader";

export const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn("[&_tr:last-child]:border-0", className)} {...props} />
));
TableBody.displayName = "TableBody";

export const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      "border-b border-border transition-colors",
      // A whisper on hover. The row the pointer is on should be findable
      // without the table looking like it is highlighting a selection.
      "hover:bg-muted/50",
      // Selection is a stronger, teal-tinted state so the two never read as
      // the same thing. Set by callers via data-state="selected".
      "data-[state=selected]:bg-primary-050",
      className,
    )}
    {...props}
  />
));
TableRow.displayName = "TableRow";

export const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    className={cn(
      "h-11 whitespace-nowrap px-3 text-left align-middle",
      "text-label uppercase text-muted-foreground",
      // Pins to the top of the scroll container when the Table has a
      // maxHeight, and is inert otherwise. An opaque background is required:
      // without it the rows scroll visibly underneath the header text.
      "sticky top-0 z-10 bg-surface",
      className,
    )}
    {...props}
  />
));
TableHead.displayName = "TableHead";

export const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  // py-3.5 against the 23px line box of 15px/1.55 text gives a ~52px row, which
  // sits mid-band rather than at the 48px floor. The extra three pixels came
  // from the type change, and are worth keeping: these tables are read down a
  // long column rather than skimmed a few rows at a time.
  <td ref={ref} className={cn("px-3 py-3.5 align-middle", className)} {...props} />
));
TableCell.displayName = "TableCell";

export const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
  <caption ref={ref} className={cn("mt-3 text-xs text-muted-foreground", className)} {...props} />
));
TableCaption.displayName = "TableCaption";
