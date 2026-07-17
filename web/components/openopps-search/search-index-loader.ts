import type {
	Entity,
	JobsSearchResponse,
	JobsSearchSummaryResponse,
	LineageAggregate,
	SearchChunk,
	SearchChunkRef,
	SearchManifest,
	SearchRow,
} from "./search-types";
import type {
	JobBoardFilters,
	JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import {
	EXPECTED_COLUMNS,
	SEARCH_VERSION,
	SearchLoadError,
	expectedColumnsFor,
} from "./search-utils";

export const SEARCH_MANIFEST_PATH = "/data/openopps-search/manifest.json";
export const JOBS_SEARCH_PATH = "/api/jobs/search";
export const LINEAGE_AGGREGATE_PATH = "/data/openopps-search/lineage-aggregate.json";
const SUPPORTED_SEARCH_INDEX_VERSIONS = new Set([3, SEARCH_VERSION]);
const MAX_CHUNK_FETCHES = 6;

const jsonCache = new Map<string, Promise<unknown>>();

export async function fetchJson<T>(path: string): Promise<T> {
	let cached = jsonCache.get(path);
	if (!cached) {
		cached = fetch(path, { cache: "force-cache" }).then(async (response) => {
			if (!response.ok) {
				throw new SearchLoadError(
					"fetch_failed",
					`Unable to load ${path}: ${response.status}`,
					path,
				);
			}
			return response.json() as Promise<unknown>;
		});
		cached = cached.catch((caught: unknown) => {
			if (jsonCache.get(path) === cached) {
				jsonCache.delete(path);
			}
			throw caught;
		});
		jsonCache.set(path, cached);
	}
	return cached as Promise<T>;
}

export async function loadSearchManifest(path = SEARCH_MANIFEST_PATH) {
	const manifest = await fetchJson<SearchManifest>(path);
	validateCachedJson(path, manifest, validateSearchManifest);
	return manifest;
}

export async function loadInitialJobsChunk(manifest: SearchManifest) {
	const entity = manifest.entities.jobs;
	const path = entity.initialPath ?? entity.path;
	if (!path) {
		return loadEntityChunk(manifest, "jobs");
	}
	const chunk = await fetchJson<SearchChunk>(path);
	validateCachedJson(path, chunk, (value) => validateSearchChunk("jobs", value));
	return chunk;
}

export async function loadEntityChunk(manifest: SearchManifest, entity: Entity) {
	const details = manifest.entities[entity];
	if (details.chunks?.length) {
		const chunks = await loadChunkRefs(entity, details.chunks);
		const rows = chunks.flatMap((chunk) => chunk.rows);
		return {
			version: manifest.version,
			entity,
			columns: details.columns,
			count: rows.length,
			rows,
		} satisfies SearchChunk;
	}
	if (!details.path) {
		throw new SearchLoadError(
			"missing_entity_path",
			`Search manifest is missing ${entity} entity path.`,
		);
	}
	const chunk = await fetchJson<SearchChunk>(details.path);
	validateCachedJson(details.path, chunk, (value) => validateSearchChunk(entity, value));
	return chunk;
}

export async function loadLineageAggregate(manifest: SearchManifest) {
	const path = manifest.lineageAggregate?.path ?? LINEAGE_AGGREGATE_PATH;
	const aggregate = await fetchJson<LineageAggregate>(path);
	validateCachedJson(path, aggregate, validateLineageAggregate);
	return aggregate;
}

export async function loadJobsSearchResults(
	filters: JobBoardFilters,
	sortKey: JobSortKey,
	options: { limit?: number; page?: number; pageSize?: number; signal?: AbortSignal } = {},
) {
	const params = new URLSearchParams();
	appendParam(params, "q", filters.query);
	appendBooleanParam(params, "wide", filters.wide);
	appendBooleanParam(params, "all", filters.includeAllIndexed);
	appendParam(params, "source", filters.source);
	appendParam(params, "provider", filters.provider);
	appendParam(params, "location", filters.location);
	appendParam(params, "department", filters.department);
	appendParam(params, "team", filters.team);
	appendParam(params, "workplace", filters.workplace);
	appendParam(params, "remote", filters.remote);
	appendParam(params, "employment", filters.employment);
	appendParam(params, "skill", filters.skill);
	appendParam(params, "salaryMin", filters.salaryMin);
	appendParam(params, "salaryMax", filters.salaryMax);
	appendParam(params, "postedAfter", filters.postedAfter);
	appendParam(params, "postedBefore", filters.postedBefore);
	appendParam(params, "sort", sortKey);
	if (options.limit) {
		appendParam(params, "limit", String(options.limit));
	}
	if (options.page) {
		appendParam(params, "page", String(options.page));
	}
	if (options.pageSize) {
		appendParam(params, "pageSize", String(options.pageSize));
	}
	const path = `${JOBS_SEARCH_PATH}?${params.toString()}`;
	const response = await fetch(path, {
		cache: "no-store",
		signal: options.signal,
	});
	if (!response.ok) {
		throw new SearchLoadError(
			"fetch_failed",
			`Unable to load ${JOBS_SEARCH_PATH}: ${response.status}`,
			JOBS_SEARCH_PATH,
		);
	}
	const payload = (await response.json()) as JobsSearchResponse;
	validateJobsSearchResponse(payload);
	return payload;
}

export async function loadJobsSearchSummary(
	filters: JobBoardFilters,
	sortKey: JobSortKey,
	options: { signal?: AbortSignal } = {},
) {
	const params = jobsSearchParams(filters, sortKey);
	params.set("summary", "1");
	const path = `${JOBS_SEARCH_PATH}?${params.toString()}`;
	const response = await fetch(path, {
		cache: "no-store",
		signal: options.signal,
	});
	if (!response.ok) {
		throw new SearchLoadError(
			"fetch_failed",
			`Unable to load ${JOBS_SEARCH_PATH}: ${response.status}`,
			JOBS_SEARCH_PATH,
		);
	}
	const payload = (await response.json()) as JobsSearchSummaryResponse;
	validateJobsSearchSummaryResponse(payload);
	return payload;
}

export function validateSearchManifest(manifest: SearchManifest) {
	if (!SUPPORTED_SEARCH_INDEX_VERSIONS.has(manifest.version)) {
		throw new SearchLoadError(
			"unsupported_version",
			`Unsupported search index version: ${manifest.version}`,
		);
	}
	for (const entity of Object.keys(EXPECTED_COLUMNS) as Entity[]) {
		const columns = manifest.entities?.[entity]?.columns;
		const expectedColumns = expectedColumnsFor(entity, manifest.version);
		if (!columns || columns.join("\0") !== expectedColumns.join("\0")) {
			throw new SearchLoadError(
				"invalid_manifest",
				`Search index manifest columns do not match ${entity}`,
			);
		}
	}
}

export function validateSearchChunk(entity: Entity, chunk: SearchChunk) {
	if (!SUPPORTED_SEARCH_INDEX_VERSIONS.has(chunk.version) || chunk.entity !== entity) {
		throw new SearchLoadError(
			"invalid_chunk",
			`Unsupported ${entity} search index chunk`,
		);
	}
	const expectedColumns = expectedColumnsFor(entity, chunk.version);
	if (chunk.columns.join("\0") !== expectedColumns.join("\0")) {
		throw new SearchLoadError(
			"invalid_chunk",
			`Search index chunk columns do not match ${entity}`,
		);
	}
	if (chunk.count !== chunk.rows.length) {
		throw new SearchLoadError(
			"invalid_chunk",
			`Search index chunk count does not match ${entity} rows`,
		);
	}
}

export function validateJobsSearchResponse(response: JobsSearchResponse) {
	validateSearchChunk("jobs", response);
	if (
		typeof response.totalMatches !== "number" ||
		typeof response.limit !== "number" ||
		typeof response.page !== "number" ||
		typeof response.pageSize !== "number" ||
		typeof response.totalPages !== "number" ||
		typeof response.hasNextPage !== "boolean" ||
		typeof response.hasPreviousPage !== "boolean" ||
		typeof response.truncated !== "boolean"
	) {
		throw new SearchLoadError(
			"invalid_chunk",
			"Jobs search response is missing result metadata.",
		);
	}
}

export function validateJobsSearchSummaryResponse(response: JobsSearchSummaryResponse) {
	if (
		response.entity !== "jobs" ||
		!SUPPORTED_SEARCH_INDEX_VERSIONS.has(response.version) ||
		typeof response.totalMatches !== "number" ||
		typeof response.sortKey !== "string" ||
		typeof response.filtersHash !== "string" ||
		!Array.isArray(response.entries)
	) {
		throw new SearchLoadError(
			"invalid_chunk",
			"Jobs search summary response is missing result metadata.",
		);
	}
	if (response.entries.length !== response.totalMatches) {
		throw new SearchLoadError(
			"invalid_chunk",
			"Jobs search summary count does not match entries.",
		);
	}
	for (const entry of response.entries) {
		if (
			!entry ||
			typeof entry.id !== "string" ||
			typeof entry.fingerprint !== "string"
		) {
			throw new SearchLoadError(
				"invalid_chunk",
				"Jobs search summary contains an invalid entry.",
			);
		}
	}
}

export function validateLineageAggregate(aggregate: LineageAggregate) {
	if (!SUPPORTED_SEARCH_INDEX_VERSIONS.has(aggregate.version)) {
		throw new SearchLoadError(
			"unsupported_version",
			`Unsupported lineage aggregate version: ${aggregate.version}`,
		);
	}
	if (
		!aggregate.counts ||
		!aggregate.nodes ||
		!aggregate.edges ||
		!Array.isArray(aggregate.nodes.sources) ||
		!Array.isArray(aggregate.nodes.providers) ||
		!Array.isArray(aggregate.nodes.boards) ||
		!Array.isArray(aggregate.edges.sourceProviders) ||
		!Array.isArray(aggregate.edges.sourceBoards) ||
		!Array.isArray(aggregate.edges.providerBoards)
	) {
		throw new SearchLoadError(
			"invalid_chunk",
			"Lineage aggregate is missing required nodes or edges.",
		);
	}
}

export function clearSearchIndexLoaderCacheForTests() {
	jsonCache.clear();
}

async function loadChunkRefs(entity: Entity, refs: SearchChunkRef[]) {
	const orderedRefs = [...refs].sort((left, right) => left.index - right.index);
	const chunks: SearchChunk[] = new Array(orderedRefs.length);
	let cursor = 0;

	async function worker() {
		while (cursor < orderedRefs.length) {
			const index = cursor;
			cursor += 1;
			const ref = orderedRefs[index];
			const chunk = await fetchJson<SearchChunk>(ref.path);
			validateCachedJson(ref.path, chunk, (value) =>
				validateSearchChunk(entity, value),
			);
			chunks[index] = chunk;
		}
	}

	const workers = Array.from(
		{ length: Math.min(MAX_CHUNK_FETCHES, orderedRefs.length) },
		() => worker(),
	);
	await Promise.all(workers);
	return chunks;
}

function validateCachedJson<T>(
	path: string,
	value: T,
	validator: (value: T) => void,
) {
	try {
		validator(value);
	} catch (caught) {
		jsonCache.delete(path);
		throw caught;
	}
}

function appendParam(params: URLSearchParams, key: string, value: string) {
	const trimmed = value.trim();
	if (trimmed) {
		params.set(key, trimmed);
	}
}

function appendBooleanParam(params: URLSearchParams, key: string, value: boolean) {
	if (value) {
		params.set(key, "1");
	}
}

function jobsSearchParams(filters: JobBoardFilters, sortKey: JobSortKey) {
	const params = new URLSearchParams();
	appendParam(params, "q", filters.query);
	appendBooleanParam(params, "wide", filters.wide);
	appendBooleanParam(params, "all", filters.includeAllIndexed);
	appendParam(params, "source", filters.source);
	appendParam(params, "provider", filters.provider);
	appendParam(params, "location", filters.location);
	appendParam(params, "department", filters.department);
	appendParam(params, "team", filters.team);
	appendParam(params, "workplace", filters.workplace);
	appendParam(params, "remote", filters.remote);
	appendParam(params, "employment", filters.employment);
	appendParam(params, "skill", filters.skill);
	appendParam(params, "salaryMin", filters.salaryMin);
	appendParam(params, "salaryMax", filters.salaryMax);
	appendParam(params, "postedAfter", filters.postedAfter);
	appendParam(params, "postedBefore", filters.postedBefore);
	appendParam(params, "sort", sortKey);
	return params;
}
