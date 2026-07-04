import type { SearchRow } from "@/components/openopps-search/search-types";
import { J, text } from "@/components/openopps-search/search-utils";

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
