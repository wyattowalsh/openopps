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
import { resolvePublicSearchUrl } from "@/lib/public-search-url";

export const DEFAULT_JOBS_SEARCH_LIMIT = 250;
export const MAX_JOBS_SEARCH_LIMIT = 1000;
export const DEFAULT_JOBS_SEARCH_PAGE_SIZE = 50;
export const MAX_JOBS_SEARCH_PAGE_SIZE = 100;
const MAX_CHUNK_FETCHES = 6;
const FILTER_RESULT_CACHE_MAX = 48;
const PUBLIC_SEARCH_FETCH_INIT = { cache: "no-store" } satisfies RequestInit;

type SearchPublicJobsIndexOptions = {
	baseUrl: URL | string;
	filters: JobBoardFilters;
	sortKey: JobSortKey;
	limit?: number;
	page?: number;
	pageSize?: number;
	signal?: AbortSignal;
	/** When true, summary responses include per-job id/fingerprint entries (DEC-07). */
	includeFingerprints?: boolean;
};

type JobsSearchStore = {
	baseHref: string;
	manifest: SearchManifest;
	jobs: SearchManifest["entities"]["jobs"];
	rows: SearchRow[];
	openRows: SearchRow[];
	rowsById: Map<string, SearchRow>;
	cacheKey: string;
};

type JobsSearchStoreStats = {
	loads: number;
	chunkFetches: number;
};

const storeByBase = new Map<string, Promise<JobsSearchStore>>();
/** Bounded FIFO cache of ordered job ids (not full row arrays). */
const filterResultCache = new Map<string, string[]>();
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
	signal,
}: SearchPublicJobsIndexOptions): Promise<JobsSearchResponse> {
	const normalizedPage = normalizePage(page);
	const normalizedPageSize = normalizePageSize(pageSize ?? limit);
	const store = await loadJobsSearchStore(baseUrl, signal);
	const sortedRows = getFilteredSortedRows(store, filters, sortKey);
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
	includeFingerprints = false,
	signal,
}: SearchPublicJobsIndexOptions): Promise<JobsSearchSummaryResponse> {
	const store = await loadJobsSearchStore(baseUrl, signal);
	const rows = getFilteredSortedRows(store, filters, sortKey);
	const entries = includeFingerprints
		? rows
				.map((row) => ({
					id: text(row[J.id]),
					fingerprint: jobFingerprint(row),
				}))
				.filter((entry) => entry.id)
		: [];
	return {
		version: store.manifest.version,
		entity: "jobs",
		totalMatches: rows.length,
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
	filterResultCache.clear();
	storeStats.loads = 0;
	storeStats.chunkFetches = 0;
}

export function jobsSearchStoreStatsForTests() {
	return { ...storeStats };
}

async function loadJobsSearchStore(
	baseUrl: URL | string,
	signal?: AbortSignal,
): Promise<JobsSearchStore> {
	const base = normalizeBaseUrl(baseUrl);
	const baseHref = base.href;
	// Abortable loads bypass the shared promise cache so a cancelled request cannot poison others.
	if (signal) {
		return buildJobsSearchStore(base, signal);
	}
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

async function buildJobsSearchStore(
	base: URL,
	signal?: AbortSignal,
): Promise<JobsSearchStore> {
	storeStats.loads += 1;
	const manifest = await loadPublicJson<SearchManifest>(
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
	const chunks = await loadChunkRefs(base, refs, signal);
	const rows = chunks.flatMap((chunk) => chunk.rows);
	const rowsById = new Map<string, SearchRow>();
	for (const row of rows) {
		const id = text(row[J.id]);
		if (id) {
			rowsById.set(id, row);
		}
	}
	return {
		baseHref: base.href,
		manifest,
		jobs,
		rows,
		openRows: rows.filter((row) => text(row[J.status]) === "open"),
		rowsById,
		cacheKey: stableStringify({
			version: manifest.version,
			snapshotAt: manifest.snapshotAt,
			count: jobs.count,
		}),
	};
}

function filterResultCacheKey(
	store: JobsSearchStore,
	filters: JobBoardFilters,
	sortKey: JobSortKey,
) {
	return `${store.cacheKey}|${stableStringify(filters)}|${sortKey}`;
}

function getFilteredSortedRows(
	store: JobsSearchStore,
	filters: JobBoardFilters,
	sortKey: JobSortKey,
) {
	const key = filterResultCacheKey(store, filters, sortKey);
	const cachedIds = filterResultCache.get(key);
	if (cachedIds) {
		const reconstructed: SearchRow[] = [];
		let intact = true;
		for (const id of cachedIds) {
			const row = store.rowsById.get(id);
			if (!row) {
				intact = false;
				break;
			}
			reconstructed.push(row);
		}
		if (intact) {
			return reconstructed;
		}
		filterResultCache.delete(key);
	}
	const sourceRows = filters.includeAllIndexed ? store.rows : store.openRows;
	const sortedRows = filterAndSortJobs(sourceRows, filters, sortKey);
	const ids = sortedRows
		.map((row) => text(row[J.id]))
		.filter((id): id is string => Boolean(id));
	// Only cache when every row has a stable id (otherwise reconstruction is unsafe).
	if (ids.length === sortedRows.length) {
		if (filterResultCache.has(key)) {
			filterResultCache.delete(key);
		} else if (filterResultCache.size >= FILTER_RESULT_CACHE_MAX) {
			const oldest = filterResultCache.keys().next().value;
			if (oldest !== undefined) {
				filterResultCache.delete(oldest);
			}
		}
		filterResultCache.set(key, ids);
	}
	return sortedRows;
}

async function loadChunkRefs(
	base: URL,
	refs: Array<{ path: string }>,
	signal?: AbortSignal,
) {
	const chunks: SearchChunk[] = new Array(refs.length);
	let cursor = 0;
	async function worker() {
		while (cursor < refs.length) {
			if (signal?.aborted) {
				throw new DOMException("The operation was aborted.", "AbortError");
			}
			const index = cursor;
			cursor += 1;
			const ref = refs[index];
			const chunk = await loadPublicJson<SearchChunk>(base, ref.path, signal);
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

function isLoopbackBase(baseUrl: URL) {
	return (
		baseUrl.hostname === "127.0.0.1" ||
		baseUrl.hostname === "localhost" ||
		baseUrl.hostname === "::1"
	);
}

async function loadPublicJsonFromFilesystem<T>(publicPath: string): Promise<T> {
	const { readFile } = await import("node:fs/promises");
	const { join } = await import("node:path");
	const relative = publicPath.replace(/^\/+/, "");
	const filePath = join(process.cwd(), "public", relative);
	const raw = await readFile(filePath, "utf8");
	return JSON.parse(raw) as T;
}

async function loadPublicJson<T>(
	baseUrl: URL,
	publicPath: string,
	signal?: AbortSignal,
): Promise<T> {
	storeStats.chunkFetches += publicPath.includes("/jobs/chunks/") ? 1 : 0;
	try {
		const resolved = resolvePublicSearchUrl(baseUrl, publicPath);
		// Avoid flaky server-side self-HTTP against next start (IPv6/connection races).
		if (isLoopbackBase(baseUrl) || isLoopbackBase(resolved)) {
			return await loadPublicJsonFromFilesystem<T>(publicPath);
		}
		const response = await fetch(resolved, {
			...PUBLIC_SEARCH_FETCH_INIT,
			signal,
		});
		if (!response.ok) {
			throw new Error(`HTTP ${response.status}`);
		}
		return (await response.json()) as T;
	} catch (caught) {
		if (caught instanceof DOMException && caught.name === "AbortError") {
			throw caught;
		}
		if (caught instanceof Error && caught.name === "AbortError") {
			throw caught;
		}
		const detail =
			caught instanceof Error
				? `${caught.name}: ${caught.message || "(empty message)"}`
				: String(caught);
		throw new SearchLoadError(
			"fetch_failed",
			`Unable to load ${publicPath}: ${detail}`,
			publicPath,
		);
	}
}

function errorMessage(caught: unknown) {
	return caught instanceof Error ? caught.message : String(caught);
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
