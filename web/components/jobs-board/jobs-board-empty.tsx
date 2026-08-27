import { SearchX } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatCount } from "@/components/openopps-search/search-utils";

type JobsBoardEmptyProps = {
	matchCount: number;
	activeFilterCount: number;
	onClearFilters: () => void;
	loadingResults?: boolean;
};

export function JobsBoardEmpty({
	matchCount,
	activeFilterCount,
	onClearFilters,
	loadingResults = false,
}: JobsBoardEmptyProps) {
	const hasActiveFilters = activeFilterCount > 0;
	if (loadingResults) {
		return (
			<div className="opps-empty-state">
				<h2 className="font-heading text-lg font-semibold text-foreground">
					Searching open jobs
				</h2>
				<p className="mt-2 max-w-md text-sm leading-6">
					Fetching matching rows for the active filters.
				</p>
			</div>
		);
	}

	return (
		<div className="opps-empty-state">
			<SearchX className="mb-4 size-10 text-muted-foreground/70" aria-hidden="true" />
			<h2 className="font-heading text-lg font-semibold">
				{hasActiveFilters ? "No open jobs match" : "Search or filter open jobs"}
			</h2>
			<p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
				{hasActiveFilters
					? `${formatCount(matchCount)} roles pass the open-only filter with your current constraints. ${activeFilterCount} active filter${activeFilterCount === 1 ? "" : "s"} may be too narrow.`
					: "Use the search field, filters, or all-indexed toggle to load a paginated result set from the server."}
			</p>
			{hasActiveFilters ? (
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
