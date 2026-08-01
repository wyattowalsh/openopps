import type { JobBoardFilters, JobSortKey } from "@/components/jobs-board/jobs-board-filter-engine";
import {
	baselineFromRows,
} from "@/components/jobs-board/jobs-board-local-reconcile";
import type { SavedSearchRecord } from "@/components/jobs-board/jobs-board-local-types";
import type { JobsSearchSummaryResponse, SearchRow } from "@/components/openopps-search/search-types";

export type CreateSavedSearchBaseline = {
	baseline: SavedSearchRecord["baseline"];
	baselineScope: SavedSearchRecord["baselineScope"];
	baselineTotalMatches: number | null;
	reviewStatus: SavedSearchRecord["reviewStatus"];
	reviewCursor: SavedSearchRecord["reviewCursor"];
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
	now = new Date().toISOString(),
}: {
	visibleRows: SearchRow[];
	filters: JobBoardFilters;
	sortKey: JobSortKey;
	loadSummary: LoadJobsSearchSummary;
	now?: string;
}): Promise<CreateSavedSearchBaseline> {
	let baseline = baselineFromRows(visibleRows);
	let baselineScope: SavedSearchRecord["baselineScope"] = "page";
	let baselineTotalMatches: number | null = visibleRows.length;
	let reviewStatus: SavedSearchRecord["reviewStatus"] = "needs-review";
	let reviewCursor: SavedSearchRecord["reviewCursor"] = null;
	try {
		const summary = await loadSummary(filters, sortKey);
		baselineScope = "cursor";
		baselineTotalMatches = summary.totalMatches;
		reviewStatus = "current";
		reviewCursor = {
			semantics: "first-seen-v1",
			reviewedAt: now,
			snapshotAt: summary.snapshotAt,
		};
	} catch {
		// Preserve the visible baseline, but require review before claiming full-index counts.
	}
	return {
		baseline,
		baselineScope,
		baselineTotalMatches,
		reviewStatus,
		reviewCursor,
	};
}
