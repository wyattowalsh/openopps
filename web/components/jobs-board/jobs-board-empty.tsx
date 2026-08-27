import { SearchX } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatCount } from "@/components/openopps-search/search-utils";

const EMPTY_TITLE_ID = "openopps-jobs-empty-title";

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
			<div
				className="opps-empty-state"
				role="region"
				aria-labelledby={EMPTY_TITLE_ID}
				aria-busy="true"
			>
				<h2
					id={EMPTY_TITLE_ID}
					className="font-heading text-lg font-semibold text-foreground"
				>
					{hasActiveFilters ? "Searching open jobs" : "Loading open jobs"}
				</h2>
				<p className="mt-2 max-w-md text-sm leading-6">
					{hasActiveFilters
						? "Fetching matching rows for the active filters."
						: "Fetching the latest open roles."}
				</p>
			</div>
		);
	}

	return (
		<div
			className="opps-empty-state"
			role="region"
			aria-labelledby={EMPTY_TITLE_ID}
		>
			<SearchX
				className="mb-4 size-10 text-muted-foreground/70"
				aria-hidden="true"
			/>
			<h2 id={EMPTY_TITLE_ID} className="font-heading text-lg font-semibold">
				{hasActiveFilters ? "No open jobs match" : "No open jobs"}
			</h2>
			<p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
				{hasActiveFilters
					? `${formatCount(matchCount)} roles pass the open-only filter with your current constraints. ${activeFilterCount} active filter${activeFilterCount === 1 ? "" : "s"} may be too narrow.`
					: "The current snapshot has no open roles to list."}
			</p>
			{hasActiveFilters ? (
				<Button
					type="button"
					variant="outline"
					size="default"
					className="mt-4 min-h-11 min-w-11 px-3"
					onClick={onClearFilters}
				>
					Clear filters
				</Button>
			) : null}
		</div>
	);
}
