import {
	DEFAULT_JOB_BOARD_FILTERS,
	filterAndSortJobs,
	jobMatchesFilters,
	type JobBoardFilters,
	type JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import {
	SEARCH_MANIFEST_PATH,
	validateSearchChunk,
	validateSearchManifest,
} from "@/components/openopps-search/search-index-loader";
import type {
	JobsSearchResponse,
	SearchChunk,
	SearchManifest,
	SearchRow,
} from "@/components/openopps-search/search-types";
import { SearchLoadError } from "@/components/openopps-search/search-utils";

export const DEFAULT_JOBS_SEARCH_LIMIT = 250;
export const MAX_JOBS_SEARCH_LIMIT = 1000;
export const DEFAULT_JOBS_SEARCH_PAGE_SIZE = 50;
export const MAX_JOBS_SEARCH_PAGE_SIZE = 100;
const MAX_CHUNK_FETCHES = 6;

type SearchPublicJobsIndexOptions = {
	baseUrl: URL | string;
	filters: JobBoardFilters;
	sortKey: JobSortKey;
	limit?: number;
	page?: number;
	pageSize?: number;
	signal?: AbortSignal;
};

export async function searchPublicJobsIndex({
	baseUrl,
	filters,
	sortKey,
	limit = DEFAULT_JOBS_SEARCH_LIMIT,
	page,
	pageSize,
	signal,
}: SearchPublicJobsIndexOptions): Promise<JobsSearchResponse> {
	const normalizedPage = normalizePage(page);
	const normalizedPageSize = normalizePageSize(pageSize ?? limit);
	const base = normalizeBaseUrl(baseUrl);
	const manifest = await fetchPublicJson<SearchManifest>(
		base,
		SEARCH_MANIFEST_PATH,
		signal,
	);
	validateSearchManifest(manifest);

	const jobs = manifest.entities.jobs;
	const refs = jobs.chunks?.length
		? [...jobs.chunks].sort((left, right) => left.index - right.index)
		: jobs.path
			? [{ index: 0, path: jobs.path, file: jobs.file ?? "jobs.json", count: jobs.count }]
			: [];

	if (refs.length === 0) {
		throw new SearchLoadError(
			"missing_entity_path",
			"Search manifest is missing jobs entity chunks.",
		);
	}

	let cursor = 0;
	let totalMatches = 0;
	const matchedRows: SearchRow[] = [];

	async function worker() {
		while (cursor < refs.length) {
			const ref = refs[cursor];
			cursor += 1;
			const chunk = await fetchPublicJson<SearchChunk>(base, ref.path, signal);
			validateSearchChunk("jobs", chunk);
			const chunkMatches = chunk.rows.filter((row) =>
				jobMatchesFilters(row, filters),
			);
			totalMatches += chunkMatches.length;
			matchedRows.push(...chunkMatches);
		}
	}

	const workers = Array.from(
		{ length: Math.min(MAX_CHUNK_FETCHES, refs.length) },
		() => worker(),
	);
	await Promise.all(workers);

	const sortedRows = filterAndSortJobs(matchedRows, filters, sortKey);
	const totalPages = Math.max(1, Math.ceil(totalMatches / normalizedPageSize));
	const safePage = Math.min(normalizedPage, totalPages);
	const start = (safePage - 1) * normalizedPageSize;
	const rows = sortedRows.slice(start, start + normalizedPageSize);
	return {
		version: manifest.version,
		entity: "jobs",
		columns: jobs.columns,
		count: rows.length,
		rows,
		totalMatches,
		limit: normalizedPageSize,
		page: safePage,
		pageSize: normalizedPageSize,
		totalPages,
		hasNextPage: safePage < totalPages,
		hasPreviousPage: safePage > 1,
		truncated: totalMatches > rows.length,
	};
}

export function normalizeJobsSearchFilters(
	filters: Partial<JobBoardFilters>,
): JobBoardFilters {
	return {
		...DEFAULT_JOB_BOARD_FILTERS,
		...filters,
		wide: Boolean(filters.wide),
		includeAllIndexed: Boolean(filters.includeAllIndexed),
	};
}

export function normalizeJobsSearchSortKey(
	value: string | null | undefined,
	filters: JobBoardFilters,
): JobSortKey {
	if (value === "latest" || value === "relevance") {
		return value;
	}
	return filters.query ? "relevance" : "latest";
}

export function normalizeLimit(value: number | string | null | undefined) {
	const numeric = typeof value === "number" ? value : Number(value);
	if (!Number.isFinite(numeric)) {
		return DEFAULT_JOBS_SEARCH_LIMIT;
	}
	return Math.min(Math.max(Math.trunc(numeric), 1), MAX_JOBS_SEARCH_LIMIT);
}

export function normalizePage(value: number | string | null | undefined) {
	const numeric = typeof value === "number" ? value : Number(value);
	if (!Number.isFinite(numeric)) {
		return 1;
	}
	return Math.max(Math.trunc(numeric), 1);
}

export function normalizePageSize(value: number | string | null | undefined) {
	const numeric = typeof value === "number" ? value : Number(value);
	if (!Number.isFinite(numeric)) {
		return DEFAULT_JOBS_SEARCH_PAGE_SIZE;
	}
	return Math.min(Math.max(Math.trunc(numeric), 1), MAX_JOBS_SEARCH_PAGE_SIZE);
}

async function fetchPublicJson<T>(
	baseUrl: URL,
	path: string,
	signal?: AbortSignal,
): Promise<T> {
	const response = await fetch(new URL(path, baseUrl), {
		cache: "no-store",
		signal,
	});
	if (!response.ok) {
		throw new SearchLoadError(
			"fetch_failed",
			`Unable to load ${path}: ${response.status}`,
			path,
		);
	}
	return response.json() as Promise<T>;
}

function normalizeBaseUrl(baseUrl: URL | string) {
	const parsed = baseUrl instanceof URL ? baseUrl : new URL(baseUrl);
	return new URL("/", parsed);
}
