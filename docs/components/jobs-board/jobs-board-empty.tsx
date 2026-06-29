import { SearchX } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatCount } from "@/components/openopps-search/search-utils";

type JobsBoardEmptyProps = {
	matchCount: number;
	activeFilterCount: number;
	onClearFilters: () => void;
};

export function JobsBoardEmpty({
	matchCount,
	activeFilterCount,
	onClearFilters,
}: JobsBoardEmptyProps) {
	return (
		<div className="opps-empty">
			<SearchX className="mb-4 size-10 text-muted-foreground/70" />
			<h2 className="font-heading text-lg font-semibold">No open jobs match</h2>
			<p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
				{formatCount(matchCount)} roles pass the open-only filter with your current
				constraints.
				{activeFilterCount > 0
					? ` ${activeFilterCount} active filter${activeFilterCount === 1 ? "" : "s"} may be too narrow.`
					: " Try widening the search query or clearing location constraints."}
			</p>
			{activeFilterCount > 0 ? (
				<Button
					type="button"
					variant="outline"
					size="sm"
					className="mt-4"
					onClick={onClearFilters}
				>
					Clear filters
				</Button>
			) : null}
		</div>
	);
}