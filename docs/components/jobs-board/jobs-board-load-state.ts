import type { SearchRow } from "@/components/openopps-search/search-types";
import { J, text } from "@/components/openopps-search/search-utils";

type FullIndexDecision = {
	activeFilterCount: number;
	rows: SearchRow[];
	selectedJobId?: string | null;
	fullIndexError?: string | null;
};

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
}: FullIndexDecision) {
	if (fullIndexError) {
		return false;
	}
	if (activeFilterCount > 0) {
		return true;
	}
	if (!selectedJobId) {
		return false;
	}
	return findJobRowById(rows, selectedJobId) === null;
}
