import type { JobBoardFilters, JobSortKey } from "@/components/jobs-board/jobs-board-filter-engine";
import {
	baselineFromRows,
	baselineFromSearchSummary,
} from "@/components/jobs-board/jobs-board-local-reconcile";
import type { SavedSearchRecord } from "@/components/jobs-board/jobs-board-local-types";
import type { JobsSearchSummaryResponse, SearchRow } from "@/components/openopps-search/search-types";

export type CreateSavedSearchBaseline = {
	baseline: SavedSearchRecord["baseline"];
	baselineScope: SavedSearchRecord["baselineScope"];
	baselineTotalMatches: number | null;
};

export type LoadJobsSearchSummary = (
	filters: JobBoardFilters,
	sortKey: JobSortKey,
) => Promise<JobsSearchSummaryResponse>;

export async function resolveCreateSavedSearchBaseline({
	visibleRows,
	filters,
	sortKey,
	loadSummary,
}: {
	visibleRows: SearchRow[];
	filters: JobBoardFilters;
	sortKey: JobSortKey;
	loadSummary: LoadJobsSearchSummary;
}): Promise<CreateSavedSearchBaseline> {
	let baseline = baselineFromRows(visibleRows);
	let baselineScope: SavedSearchRecord["baselineScope"] = "page";
	let baselineTotalMatches: number | null = visibleRows.length;
	try {
		const summary = await loadSummary(filters, sortKey);
		baseline = baselineFromSearchSummary(summary);
		baselineScope = "full";
		baselineTotalMatches = summary.totalMatches;
	} catch {
		// Fall back to page baseline so saves still work if summary is slow/unavailable.
	}
	return { baseline, baselineScope, baselineTotalMatches };
}
