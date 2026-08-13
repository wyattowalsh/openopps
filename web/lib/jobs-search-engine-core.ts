import {
	DEFAULT_JOB_BOARD_FILTERS,
	filterAndSortJobs,
	jobMatchesFilters,
	type JobBoardFilters,
	type JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import type {
	JobsSearchResponse,
	JobsSearchSummaryResponse,
	SavedSearchCountQuery,
	SavedSearchCountsResponse,
	SearchManifest,
	SearchRow,
} from "@/components/openopps-search/search-types";
import {
	J,
	normalizeSuggestion,
	parseSourceKeys,
	text,
} from "@/components/openopps-search/search-utils";

export const DEFAULT_JOBS_SEARCH_LIMIT = 250;
export const MAX_JOBS_SEARCH_LIMIT = 1000;
export const DEFAULT_JOBS_SEARCH_PAGE_SIZE = 50;
export const MAX_JOBS_SEARCH_PAGE_SIZE = 100;

export type FrozenSearchCase = {
	id: string;
	filters: JobBoardFilters;
	sortKey: JobSortKey;
	page: number;
	pageSize: number;
};

/** Deterministic semantic/performance corpus shared by tests and the benchmark. */
export function createFrozenJobsSearchCorpus(rowCount = 12_000) {
	const companies = ["Acme", "Nimbus", "Orbital", "Vertex"];
	const departments = ["Engineering", "Revenue", "Operations", "Research"];
	const teams = ["Platform", "Infrastructure", "Enterprise", "Machine Learning"];
	const providers = ["greenhouse", "lever", "workday", "ashby"];
	const locations = ["San Francisco, CA", "New York, NY", "London, UK", "Remote"];
	const rows: SearchRow[] = [];
	for (let index = 0; index < rowCount; index += 1) {
		const row: SearchRow = new Array(30).fill(null);
		row[J.id] = `frozen-${String(index).padStart(6, "0")}`;
		row[J.source] = index % 2 === 0 ? "a16z" : "yc";
		row[J.board] = `board-${index % 40}`;
		row[J.provider] = providers[index % providers.length];
		row[J.status] = index % 7 === 0 ? "closed" : "open";
		row[J.title] = `${index % 3 === 0 ? "Platform" : "Product"} Engineer ${index % 50}`;
		row[J.company] = companies[index % companies.length];
		row[J.department] = departments[index % departments.length];
		row[J.team] = teams[index % teams.length];
		row[J.workplace] = index % 3 === 0 ? "Remote" : index % 3 === 1 ? "Hybrid" : "On-site";
		row[J.remote] = index % 3 === 0 ? "remote" : index % 3 === 1 ? "hybrid" : "onsite";
		row[J.type] = index % 5 === 0 ? "Part-time" : "Full-time";
		row[J.locations] = JSON.stringify([locations[index % locations.length]]);
		row[J.salaryMin] = index % 11 === 0 ? null : 70_000 + (index % 9) * 10_000;
		row[J.salaryMax] = index % 11 === 0 ? null : 100_000 + (index % 9) * 10_000;
		row[J.currency] = "USD";
		row[J.url] = `https://example.test/jobs/${index}`;
		row[J.posted] = `2026-06-${String((index % 28) + 1).padStart(2, "0")}T00:00:00Z`;
		row[J.latestObserved] = `2026-07-${String((index % 28) + 1).padStart(2, "0")}T12:00:00.${String(index % 1000).padStart(3, "0")}Z`;
		row[J.sourceKeys] = JSON.stringify(index % 13 === 0 ? ["a16z", "accel"] : [row[J.source]]);
		row[J.descriptionSnippet] =
			index % 3 === 0
				? "Build reliable platform services with Python and Kubernetes."
				: "Ship customer-facing products with TypeScript.";
		row[J.skillTokens] = index % 3 === 0 ? "python kubernetes aws" : "typescript react sql";
		row[J.syncedAt] = row[J.latestObserved];
		row[J.firstSeenAt] = `2026-05-${String((index % 28) + 1).padStart(2, "0")}T00:00:00Z`;
		rows.push(row);
	}
	return rows;
}

export function frozenJobsSearchCases(): FrozenSearchCase[] {
	const make = (filters: Partial<JobBoardFilters>) => ({
		...DEFAULT_JOB_BOARD_FILTERS,
		...filters,
	});
	return [
		{ id: "open-latest", filters: make({}), sortKey: "latest", page: 1, pageSize: 50 },
		{
			id: "query-relevance",
			filters: make({ query: "platform" }),
			sortKey: "relevance",
			page: 2,
			pageSize: 50,
		},
		{
			id: "wide-query",
			filters: make({ query: "greenhouse", wide: true, includeAllIndexed: true }),
			sortKey: "relevance",
			page: 1,
			pageSize: 100,
		},
		{
			id: "fuzzy-facets",
			filters: make({ source: "a1", provider: "grnhse", skill: "kube" }),
			sortKey: "latest",
			page: 1,
			pageSize: 50,
		},
		{
			id: "range-intersection",
			filters: make({
				salaryMin: "120000",
				salaryMax: "170000",
				postedAfter: "2026-06-10",
				postedBefore: "2026-06-20",
			}),
			sortKey: "latest",
			page: 1,
			pageSize: 50,
		},
	];
}

const FILTER_RESULT_CACHE_MAX = 48;
export const MAX_FILTER_RESULT_CACHE_ROW_REFERENCES = 250_000;
const COOPERATIVE_BATCH_SIZE = 2048;

type PostingIndex = Map<string, Uint32Array>;

type JobsSearchEngineInput = {
	manifest: SearchManifest;
	rows: SearchRow[];
	maxCachedRowReferences?: number;
};

type JobsSearchOptions = {
	filters: JobBoardFilters;
	sortKey: JobSortKey;
	limit?: number;
	page?: number;
	pageSize?: number;
};

type CooperativeOptions = JobsSearchOptions & {
	signal?: AbortSignal;
};

/**
 * Session-local search engine used inside the jobs Web Worker.
 *
 * The engine keeps compact integer posting lists for fuzzy facets and uses a
 * transient bitset to intersect those lists. The final predicate and ordering
 * deliberately reuse the public jobs-board oracle so the optimization cannot
 * silently change user-visible semantics.
 */
export class JobsSearchEngine {
	readonly manifest: SearchManifest;
	readonly rows: SearchRow[];
	private readonly openMask: Uint32Array;
	private readonly allMask: Uint32Array;
	private readonly postings: Record<FacetKey, PostingIndex>;
	private readonly resultCache = new Map<string, SearchRow[]>();
	private readonly maxCachedRowReferences: number;
	private cachedRowRefs = 0;
	private readonly indexBytes: number;

	constructor({
		manifest,
		rows,
		maxCachedRowReferences = MAX_FILTER_RESULT_CACHE_ROW_REFERENCES,
	}: JobsSearchEngineInput) {
		if (!Number.isInteger(maxCachedRowReferences) || maxCachedRowReferences < 1) {
			throw new Error("maxCachedRowReferences must be a positive integer");
		}
		this.manifest = manifest;
		this.rows = rows;
		this.maxCachedRowReferences = maxCachedRowReferences;
		this.allMask = fullMask(rows.length);
		this.openMask = emptyMask(rows.length);
		const builders = createPostingBuilders();

		for (let index = 0; index < rows.length; index += 1) {
			const row = rows[index];
			if (text(row[J.status]) === "open") {
				setBit(this.openMask, index);
			}
			indexRow(builders, row, index);
		}

		this.postings = finishPostingBuilders(builders);
		this.indexBytes =
			this.allMask.byteLength +
			this.openMask.byteLength +
			Object.values(this.postings).reduce(
				(total, posting) =>
					total +
					[...posting.values()].reduce(
						(fieldTotal, indices) => fieldTotal + indices.byteLength,
						0,
					),
				0,
			);
	}

	search(options: JobsSearchOptions): JobsSearchResponse {
		const rows = this.filteredRows(options.filters, options.sortKey);
		return this.toSearchResponse(rows, options);
	}

	async searchCooperative(options: CooperativeOptions): Promise<JobsSearchResponse> {
		const rows = await this.filteredRowsCooperative(
			options.filters,
			options.sortKey,
			options.signal,
		);
		return this.toSearchResponse(rows, options);
	}

	summary(
		filters: JobBoardFilters,
		sortKey: JobSortKey,
	): JobsSearchSummaryResponse {
		const rows = this.filteredRows(filters, sortKey);
		return this.toSummary(rows.length, filters, sortKey);
	}

	async summaryCooperative(
		filters: JobBoardFilters,
		sortKey: JobSortKey,
		signal?: AbortSignal,
	): Promise<JobsSearchSummaryResponse> {
		const rows = await this.filteredRowsCooperative(filters, sortKey, signal);
		return this.toSummary(rows.length, filters, sortKey);
	}

	countSavedSearches(searches: SavedSearchCountQuery[]): SavedSearchCountsResponse {
		return this.toSavedSearchCounts(
			searches.map((search) => ({
				search,
				rows: this.filteredRows(search.filters, search.sortKey),
			})),
		);
	}

	async countSavedSearchesCooperative(
		searches: SavedSearchCountQuery[],
		signal?: AbortSignal,
	): Promise<SavedSearchCountsResponse> {
		const matches: Array<{ search: SavedSearchCountQuery; rows: SearchRow[] }> = [];
		for (const search of searches) {
			throwIfAborted(signal);
			matches.push({
				search,
				rows: await this.filteredRowsCooperative(
					search.filters,
					search.sortKey,
					signal,
				),
			});
		}
		return this.toSavedSearchCounts(matches);
	}

	stats() {
		return {
			rows: this.rows.length,
			indexBytes: this.indexBytes,
			cachedResults: this.resultCache.size,
			cachedRowReferences: this.cachedRowRefs,
			maxCachedRowReferences: this.maxCachedRowReferences,
			dictionaryValues: Object.values(this.postings).reduce(
				(total, posting) => total + posting.size,
				0,
			),
		};
	}

	/** Deterministic benchmark/test hook; production sessions keep the bounded cache. */
	clearResultCacheForTests() {
		this.resultCache.clear();
		this.cachedRowRefs = 0;
	}

	private filteredRows(filters: JobBoardFilters, sortKey: JobSortKey) {
		const normalizedFilters = normalizeJobsSearchFilters(filters);
		const cacheKey = `${stableStringify(normalizedFilters)}|${sortKey}`;
		const cached = this.resultCache.get(cacheKey);
		if (cached) {
			return cached;
		}
		const candidates = this.candidateRows(normalizedFilters);
		const rows = filterAndSortJobs(candidates, normalizedFilters, sortKey);
		this.cacheRows(cacheKey, rows);
		return rows;
	}

	private async filteredRowsCooperative(
		filters: JobBoardFilters,
		sortKey: JobSortKey,
		signal?: AbortSignal,
	) {
		const normalizedFilters = normalizeJobsSearchFilters(filters);
		const cacheKey = `${stableStringify(normalizedFilters)}|${sortKey}`;
		const cached = this.resultCache.get(cacheKey);
		if (cached) {
			throwIfAborted(signal);
			return cached;
		}
		const mask = this.candidateMask(normalizedFilters);
		const matches: SearchRow[] = [];
		let visited = 0;
		for (const index of setBitIndices(mask, this.rows.length)) {
			if (jobMatchesFilters(this.rows[index], normalizedFilters)) {
				matches.push(this.rows[index]);
			}
			visited += 1;
			if (visited % COOPERATIVE_BATCH_SIZE === 0) {
				await yieldToWorkerEventLoop();
				throwIfAborted(signal);
			}
		}
		throwIfAborted(signal);
		const rows = filterAndSortJobs(matches, normalizedFilters, sortKey);
		throwIfAborted(signal);
		this.cacheRows(cacheKey, rows);
		return rows;
	}

	private candidateRows(filters: JobBoardFilters) {
		const rows: SearchRow[] = [];
		const mask = this.candidateMask(filters);
		forEachSetBit(mask, this.rows.length, (index) => rows.push(this.rows[index]));
		return rows;
	}

	private candidateMask(filters: JobBoardFilters) {
		const candidate = new Uint32Array(
			filters.includeAllIndexed ? this.allMask : this.openMask,
		);
		intersectFacet(candidate, this.postings.source, filters.source);
		intersectFacet(candidate, this.postings.provider, filters.provider);
		intersectFacet(candidate, this.postings.location, filters.location);
		intersectFacet(candidate, this.postings.department, filters.department);
		intersectFacet(candidate, this.postings.team, filters.team);
		intersectFacet(candidate, this.postings.workplace, filters.workplace);
		intersectFacet(candidate, this.postings.remote, filters.remote);
		intersectFacet(candidate, this.postings.employment, filters.employment);
		intersectFacet(candidate, this.postings.skill, filters.skill);
		return candidate;
	}

	private cacheRows(key: string, rows: SearchRow[]) {
		if (rows.length > this.maxCachedRowReferences) {
			return;
		}
		const existing = this.resultCache.get(key);
		if (existing) {
			this.cachedRowRefs -= existing.length;
			this.resultCache.delete(key);
		}
		while (
			this.resultCache.size >= FILTER_RESULT_CACHE_MAX ||
			this.cachedRowRefs + rows.length > this.maxCachedRowReferences
		) {
			const oldest = this.resultCache.keys().next().value;
			if (oldest !== undefined) {
				this.cachedRowRefs -= this.resultCache.get(oldest)?.length ?? 0;
				this.resultCache.delete(oldest);
			} else {
				break;
			}
		}
		this.resultCache.set(key, rows);
		this.cachedRowRefs += rows.length;
	}

	private toSearchResponse(
		rows: SearchRow[],
		options: Pick<JobsSearchOptions, "limit" | "page" | "pageSize">,
	): JobsSearchResponse {
		const pageSize = normalizePageSize(
			options.pageSize ?? options.limit ?? DEFAULT_JOBS_SEARCH_LIMIT,
		);
		const totalMatches = rows.length;
		const totalPages = Math.max(1, Math.ceil(totalMatches / pageSize));
		const page = Math.min(normalizePage(options.page), totalPages);
		const start = (page - 1) * pageSize;
		const pageRows = rows.slice(start, start + pageSize);
		return {
			version: this.manifest.version,
			entity: "jobs",
			columns: this.manifest.entities.jobs.columns,
			count: pageRows.length,
			rows: pageRows,
			totalMatches,
			limit: pageSize,
			page,
			pageSize,
			totalPages,
			hasNextPage: page < totalPages,
			hasPreviousPage: page > 1,
			truncated: totalMatches > pageRows.length,
		};
	}

	private toSummary(
		totalMatches: number,
		filters: JobBoardFilters,
		sortKey: JobSortKey,
	): JobsSearchSummaryResponse {
		return {
			version: this.manifest.version,
			entity: "jobs",
			snapshotAt: this.manifest.snapshotAt,
			totalMatches,
			sortKey,
			filtersHash: stableStringify(normalizeJobsSearchFilters(filters)),
		};
	}

	private toSavedSearchCounts(
		matches: Array<{ search: SavedSearchCountQuery; rows: SearchRow[] }>,
	): SavedSearchCountsResponse {
		return {
			version: this.manifest.version,
			entity: "jobs",
			snapshotAt: this.manifest.snapshotAt,
			semantics: "first-seen-v1",
			counts: matches.map(({ search, rows }) => {
				const reviewedAt = Date.parse(search.reviewedAt);
				return {
					id: search.id,
					totalMatches: rows.length,
					newMatches: rows.reduce((count, row) => {
						const firstSeenAt = Date.parse(text(row[J.firstSeenAt]));
						return Number.isFinite(firstSeenAt) && firstSeenAt > reviewedAt
							? count + 1
							: count;
					}, 0),
				};
			}),
		};
	}
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

type FacetKey =
	| "source"
	| "provider"
	| "location"
	| "department"
	| "team"
	| "workplace"
	| "remote"
	| "employment"
	| "skill";

type PostingBuilders = Record<FacetKey, Map<string, number[]>>;

function createPostingBuilders(): PostingBuilders {
	return {
		source: new Map(),
		provider: new Map(),
		location: new Map(),
		department: new Map(),
		team: new Map(),
		workplace: new Map(),
		remote: new Map(),
		employment: new Map(),
		skill: new Map(),
	};
}

function indexRow(builders: PostingBuilders, row: SearchRow, index: number) {
	const sourceKeys = parseSourceKeys(row[J.sourceKeys]);
	addPostingValues(
		builders.source,
		sourceKeys.length > 0 ? sourceKeys : [text(row[J.source])],
		index,
	);
	addPostingValues(builders.provider, [text(row[J.provider])], index);
	addPostingValues(builders.location, [locationsText(row[J.locations])], index);
	addPostingValues(builders.department, [text(row[J.department])], index);
	addPostingValues(builders.team, [text(row[J.team])], index);
	addPostingValues(
		builders.workplace,
		[text(row[J.workplace]), text(row[J.remote])],
		index,
	);
	addPostingValues(builders.remote, [text(row[J.remote])], index);
	addPostingValues(builders.employment, [text(row[J.type])], index);
	addPostingValues(builders.skill, [text(row[J.skillTokens])], index);
}

function addPostingValues(
	builder: Map<string, number[]>,
	values: string[],
	index: number,
) {
	for (const raw of new Set(values)) {
		const value = normalizeSuggestion(raw);
		if (!value) {
			continue;
		}
		const postings = builder.get(value);
		if (postings) {
			postings.push(index);
		} else {
			builder.set(value, [index]);
		}
	}
}

function finishPostingBuilders(builders: PostingBuilders) {
	return Object.fromEntries(
		Object.entries(builders).map(([key, builder]) => [
			key,
			new Map(
				[...builder].map(([value, indices]) => [value, Uint32Array.from(indices)]),
			),
		]),
	) as Record<FacetKey, PostingIndex>;
}

function intersectFacet(mask: Uint32Array, posting: PostingIndex, rawNeedle: string) {
	const needle = normalizeSuggestion(rawNeedle);
	if (!needle) {
		return;
	}
	const matching = new Uint32Array(mask.length);
	for (const [value, indices] of posting) {
		if (!fuzzyMatches(value, needle)) {
			continue;
		}
		for (const index of indices) {
			setBit(matching, index);
		}
	}
	for (let index = 0; index < mask.length; index += 1) {
		mask[index] &= matching[index];
	}
}

function fuzzyMatches(value: string, needle: string) {
	return value === needle || value.includes(needle) || subsequenceMatches(value, needle);
}

function subsequenceMatches(value: string, query: string) {
	let queryIndex = 0;
	for (const char of value) {
		if (char === query[queryIndex]) {
			queryIndex += 1;
			if (queryIndex === query.length) {
				return true;
			}
		}
	}
	return false;
}

function locationsText(value: unknown) {
	const raw = text(value);
	if (!raw) {
		return "";
	}
	try {
		const parsed = JSON.parse(raw) as unknown;
		if (Array.isArray(parsed)) {
			return parsed.map((item) => text(item)).join(" ");
		}
	} catch {
		return raw;
	}
	return raw;
}

function emptyMask(rowCount: number) {
	return new Uint32Array(Math.ceil(rowCount / 32));
}

function fullMask(rowCount: number) {
	const mask = emptyMask(rowCount);
	mask.fill(0xffff_ffff);
	const remainder = rowCount % 32;
	if (remainder && mask.length > 0) {
		mask[mask.length - 1] = 0xffff_ffff >>> (32 - remainder);
	}
	return mask;
}

function setBit(mask: Uint32Array, index: number) {
	mask[index >>> 5] |= 1 << (index & 31);
}

function forEachSetBit(
	mask: Uint32Array,
	rowCount: number,
	callback: (index: number) => void,
) {
	for (let wordIndex = 0; wordIndex < mask.length; wordIndex += 1) {
		let word = mask[wordIndex] >>> 0;
		while (word !== 0) {
			const leastBit = word & -word;
			const bit = 31 - Math.clz32(leastBit);
			const index = wordIndex * 32 + bit;
			if (index < rowCount) {
				callback(index);
			}
			word = (word ^ leastBit) >>> 0;
		}
	}
}

function* setBitIndices(mask: Uint32Array, rowCount: number) {
	for (let wordIndex = 0; wordIndex < mask.length; wordIndex += 1) {
		let word = mask[wordIndex] >>> 0;
		while (word !== 0) {
			const leastBit = word & -word;
			const bit = 31 - Math.clz32(leastBit);
			const index = wordIndex * 32 + bit;
			if (index < rowCount) {
				yield index;
			}
			word = (word ^ leastBit) >>> 0;
		}
	}
}

function throwIfAborted(signal?: AbortSignal) {
	if (signal?.aborted) {
		throw new DOMException("The operation was aborted.", "AbortError");
	}
}

function yieldToWorkerEventLoop() {
	return new Promise<void>((resolve) => setTimeout(resolve, 0));
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
