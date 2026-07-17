import * as React from "react";

import { cn } from "@/lib/utils";

type SeparatorProps = React.ComponentProps<"div"> & {
	orientation?: "horizontal" | "vertical";
	decorative?: boolean;
};

function Separator({
	className,
	orientation = "horizontal",
	decorative = true,
	...props
}: SeparatorProps) {
	const semanticProps = decorative
		? { role: "none" }
		: { "aria-orientation": orientation, role: "separator" };

	return (
		<div
			data-slot="separator"
			data-orientation={orientation}
			className={cn(
				"shrink-0 bg-border",
				orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
				className,
			)}
			{...semanticProps}
			{...props}
		/>
	);
}

export { Separator };
