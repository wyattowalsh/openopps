import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
	"inline-flex shrink-0 items-center gap-1 rounded-[var(--opps-radius-md,6px)] border px-2 py-0.5 font-mono text-xs font-semibold leading-5 tracking-normal whitespace-nowrap transition-colors [&_svg]:pointer-events-none [&_svg]:size-3 [&_svg]:shrink-0",
	{
		variants: {
			variant: {
				default:
					"border-primary/35 bg-primary/10 text-primary dark:border-primary/45 dark:bg-primary/15 dark:text-primary",
				secondary:
					"border-border bg-secondary/75 text-secondary-foreground",
				outline: "border-border bg-background/70 text-foreground",
				muted: "border-border/70 bg-muted/70 text-muted-foreground",
				success: "border-success/40 bg-success/10 text-success",
				warning:
					"border-warning/45 bg-warning/15 text-warning-foreground",
				error: "border-error/40 bg-error/10 text-error",
				info: "border-info/40 bg-info/10 text-info",
			},
		},
		defaultVariants: {
			variant: "default",
		},
	},
);

function Badge({
	className,
	variant,
	...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
	return (
		<span
			data-slot="badge"
			className={cn(badgeVariants({ variant, className }))}
			{...props}
		/>
	);
}

export { Badge, badgeVariants };
