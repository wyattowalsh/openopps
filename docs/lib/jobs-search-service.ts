import {
	DEFAULT_JOB_BOARD_FILTERS,
	filterAndSortJobs,
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
	JobsSearchSummaryResponse,
} from "@/components/openopps-search/search-types";
import { J, SearchLoadError, text } from "@/components/openopps-search/search-utils";

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

type JobsSearchStore = {
	baseHref: string;
	manifest: SearchManifest;
	jobs: SearchManifest["entities"]["jobs"];
	rows: SearchRow[];
	openRows: SearchRow[];
	cacheKey: string;
};

type JobsSearchStoreStats = {
	loads: number;
	chunkFetches: number;
};

const storeByBase = new Map<string, Promise<JobsSearchStore>>();
const storeStats: JobsSearchStoreStats = {
	loads: 0,
	chunkFetches: 0,
};

export async function searchPublicJobsIndex({
	baseUrl,
	filters,
	sortKey,
	limit = DEFAULT_JOBS_SEARCH_LIMIT,
	page,
	pageSize,
}: SearchPublicJobsIndexOptions): Promise<JobsSearchResponse> {
	const normalizedPage = normalizePage(page);
	const normalizedPageSize = normalizePageSize(pageSize ?? limit);
	const store = await loadJobsSearchStore(baseUrl);
	const sortedRows = searchRows(store, filters, sortKey);
	const totalMatches = sortedRows.length;
	const totalPages = Math.max(1, Math.ceil(totalMatches / normalizedPageSize));
	const safePage = Math.min(normalizedPage, totalPages);
	const start = (safePage - 1) * normalizedPageSize;
	const rows = sortedRows.slice(start, start + normalizedPageSize);
	return {
		version: store.manifest.version,
		entity: "jobs",
		columns: store.jobs.columns,
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

export async function summarizePublicJobsIndex({
	baseUrl,
	filters,
	sortKey,
}: SearchPublicJobsIndexOptions): Promise<JobsSearchSummaryResponse> {
	const store = await loadJobsSearchStore(baseUrl);
	const rows = searchRows(store, filters, sortKey);
	const entries = rows.map((row) => ({
		id: text(row[J.id]),
		fingerprint: jobFingerprint(row),
	})).filter((entry) => entry.id);
	return {
		version: store.manifest.version,
		entity: "jobs",
		totalMatches: entries.length,
		sortKey,
		filtersHash: stableStringify(filters),
		entries,
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

export function clearJobsSearchStoreForTests() {
	storeByBase.clear();
	storeStats.loads = 0;
	storeStats.chunkFetches = 0;
}

export function jobsSearchStoreStatsForTests() {
	return { ...storeStats };
}

async function loadJobsSearchStore(baseUrl: URL | string): Promise<JobsSearchStore> {
	const base = normalizeBaseUrl(baseUrl);
	const baseHref = base.href;
	let cached = storeByBase.get(baseHref);
	if (!cached) {
		cached = buildJobsSearchStore(base).catch((caught: unknown) => {
			if (storeByBase.get(baseHref) === cached) {
				storeByBase.delete(baseHref);
			}
			throw caught;
		});
		storeByBase.set(baseHref, cached);
	}
	return cached;
}

async function buildJobsSearchStore(base: URL): Promise<JobsSearchStore> {
	storeStats.loads += 1;
	const manifest = await fetchPublicJson<SearchManifest>(base, SEARCH_MANIFEST_PATH);
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
	const chunks = await loadChunkRefs(base, refs);
	const rows = chunks.flatMap((chunk) => chunk.rows);
	return {
		baseHref: base.href,
		manifest,
		jobs,
		rows,
		openRows: rows.filter((row) => text(row[J.status]) === "open"),
		cacheKey: stableStringify({
			version: manifest.version,
			snapshotAt: manifest.snapshotAt,
			count: jobs.count,
		}),
	};
}

function searchRows(
	store: JobsSearchStore,
	filters: JobBoardFilters,
	sortKey: JobSortKey,
) {
	const rows = filters.includeAllIndexed ? store.rows : store.openRows;
	return filterAndSortJobs(rows, filters, sortKey);
}

async function loadChunkRefs(base: URL, refs: Array<{ path: string }>) {
	const chunks: SearchChunk[] = new Array(refs.length);
	let cursor = 0;
	async function worker() {
		while (cursor < refs.length) {
			const index = cursor;
			cursor += 1;
			const ref = refs[index];
			const chunk = await fetchPublicJson<SearchChunk>(base, ref.path);
			validateSearchChunk("jobs", chunk);
			chunks[index] = chunk;
		}
	}
	const workers = Array.from(
		{ length: Math.min(MAX_CHUNK_FETCHES, refs.length) },
		() => worker(),
	);
	await Promise.all(workers);
	return chunks;
}

async function fetchPublicJson<T>(
	baseUrl: URL,
	path: string,
): Promise<T> {
	storeStats.chunkFetches += path.includes("/jobs/chunks/") ? 1 : 0;
	const response = await fetch(new URL(path, baseUrl), {
		cache: "force-cache",
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

function jobFingerprint(row: SearchRow) {
	const hashFingerprint = [
		text(row[J.contentHash]),
		text(row[J.payloadHash]),
	].filter(Boolean);
	if (hashFingerprint.length) {
		return hashFingerprint.join("|");
	}
	return [
		text(row[J.id]),
		text(row[J.latestObserved]),
		text(row[J.syncedAt]),
		text(row[J.title]),
		text(row[J.company]),
		text(row[J.descriptionSnippet]),
	]
		.filter(Boolean)
		.join("|");
}

function stableStringify(value: unknown): string {
	if (!value || typeof value !== "object") {
		return JSON.stringify(value);
	}
	if (Array.isArray(value)) {
		return `[${value.map((item) => stableStringify(item)).join(",")}]`;
	}
	return `{${Object.entries(value)
		.sort(([left], [right]) => left.localeCompare(right))
		.map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`)
		.join(",")}}`;
}
