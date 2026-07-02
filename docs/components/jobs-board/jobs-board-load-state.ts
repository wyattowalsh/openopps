import type { SearchRow } from "@/components/openopps-search/search-types";
import { J, text } from "@/components/openopps-search/search-utils";

export const FULL_JOBS_INDEX_ROW_THRESHOLD = 25_000;

type FullIndexDecision = {
	activeFilterCount: number;
	rows: SearchRow[];
	selectedJobId?: string | null;
	fullIndexError?: string | null;
	jobCount?: number;
	fullIndexConfirmed?: boolean;
};

export function requiresFullJobsIndexConfirmation(jobCount: number) {
	return jobCount > FULL_JOBS_INDEX_ROW_THRESHOLD;
}

function wantsFullJobsIndex({
	activeFilterCount,
	rows,
	selectedJobId,
}: Pick<FullIndexDecision, "activeFilterCount" | "rows" | "selectedJobId">) {
	if (activeFilterCount > 0) {
		return true;
	}
	if (!selectedJobId) {
		return false;
	}
	return findJobRowById(rows, selectedJobId) === null;
}

export function needsFullJobsIndexConfirmation(decision: FullIndexDecision) {
	if (decision.fullIndexError || decision.fullIndexConfirmed) {
		return false;
	}
	if (!requiresFullJobsIndexConfirmation(decision.jobCount ?? 0)) {
		return false;
	}
	return wantsFullJobsIndex(decision);
}

export function findJobRowById(rows: SearchRow[], jobId: string) {
	const normalizedJobId = text(jobId);
	if (!normalizedJobId) {
		return null;
	}
	return rows.find((row) => text(row[J.id]) === normalizedJobId) ?? null;
}

export function resolveSelectedJobRow(
	visibleRows: SearchRow[],
	loadedRows: SearchRow[],
	selectedJobId?: string | null,
) {
	if (!selectedJobId) {
		return null;
	}
	return (
		findJobRowById(visibleRows, selectedJobId) ??
		findJobRowById(loadedRows, selectedJobId)
	);
}

export function shouldLoadFullJobsIndex({
	activeFilterCount,
	rows,
	selectedJobId,
	fullIndexError,
	jobCount = 0,
	fullIndexConfirmed = false,
}: FullIndexDecision) {
	if (fullIndexError) {
		return false;
	}
	if (!wantsFullJobsIndex({ activeFilterCount, rows, selectedJobId })) {
		return false;
	}
	if (requiresFullJobsIndexConfirmation(jobCount) && !fullIndexConfirmed) {
		return false;
	}
	return true;
}
