import {
	DEFAULT_JOB_BOARD_FILTERS,
	filterAndSortJobs,
	type JobBoardFilters,
	type JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import { JOBS_BOARD_PAGE_SIZE } from "@/components/jobs-board/jobs-board-constants";
import type { SearchChunk, SearchRow } from "@/components/openopps-search/search-types";

const EMPTY_FILTER_KEYS = [
	"query",
	"source",
	"provider",
	"location",
	"department",
	"team",
	"workplace",
	"remote",
	"employment",
	"skill",
	"salaryMin",
	"salaryMax",
	"postedAfter",
	"postedBefore",
] as const satisfies ReadonlyArray<keyof JobBoardFilters>;

export function isDefaultJobsHomeView(
	filters: JobBoardFilters,
	sortKey: JobSortKey,
	page: number,
) {
	if (page !== 1 || sortKey !== "latest") {
		return false;
	}
	if (filters.includeAllIndexed || filters.wide) {
		return false;
	}
	return EMPTY_FILTER_KEYS.every((key) => filters[key] === DEFAULT_JOB_BOARD_FILTERS[key]);
}

export function t0PageRowsFromLatest(
	latestRows: SearchRow[],
	filters: JobBoardFilters = DEFAULT_JOB_BOARD_FILTERS,
	sortKey: JobSortKey = "latest",
	pageSize: number = JOBS_BOARD_PAGE_SIZE,
) {
	return filterAndSortJobs(latestRows, filters, sortKey).slice(0, pageSize);
}

export function t0SidecarSearchMeta(options: {
	openJobCount: number;
	pageRows: SearchRow[];
	pageSize?: number;
}) {
	const pageSize = options.pageSize ?? JOBS_BOARD_PAGE_SIZE;
	const totalPages = Math.max(1, Math.ceil(Math.max(0, options.openJobCount) / pageSize));
	return {
		totalMatches: options.openJobCount,
		truncated: options.openJobCount > options.pageRows.length,
		complete: false,
		limit: pageSize,
		page: 1,
		pageSize,
		totalPages,
		hasNextPage: false,
		hasPreviousPage: false,
		labeledAsMatches: false,
	};
}

export function t0SearchChunkPage(chunk: SearchChunk, openJobCount: number) {
	const rows = t0PageRowsFromLatest(chunk.rows);
	return {
		rows,
		meta: t0SidecarSearchMeta({ openJobCount, pageRows: rows }),
	};
}
