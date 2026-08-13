import type {
	Entity,
	JobsSearchResponse,
	JobsSearchSummaryResponse,
	SavedSearchCountQuery,
	SavedSearchCountsResponse,
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
	SEARCH_VERSION,
	SearchLoadError,
} from "./search-utils";
import {
	validateSearchChunk,
	validateSearchManifest,
} from "./search-index-validation";
import { OpenOppsSnapshotClient } from "@/lib/openopps-snapshot-client";
import { getJobsOfflineSnapshotConfiguration } from "@/lib/jobs-offline-cache";

export { validateSearchChunk, validateSearchManifest } from "./search-index-validation";

export const SEARCH_MANIFEST_PATH = "/data/openopps-search/manifest.json";
export const SAVED_SEARCH_COUNT_BATCH_SIZE = 25;
export const LINEAGE_AGGREGATE_PATH = "/data/openopps-search/lineage-aggregate.json";
const SUPPORTED_SEARCH_INDEX_VERSIONS = new Set([3, SEARCH_VERSION]);
const MAX_CHUNK_FETCHES = 6;

const jsonCache = new Map<string, Promise<unknown>>();
let snapshotClientForTests: OpenOppsSnapshotClient | null | undefined;
let browserSnapshotClient: OpenOppsSnapshotClient | null | undefined;

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
	const snapshotClient = getBrowserSnapshotClient();
	const manifest =
		snapshotClient && path === SEARCH_MANIFEST_PATH
			? await snapshotClient.getSearchManifest()
			: await fetchJson<SearchManifest>(path);
	validateCachedJson(path, manifest, validateSearchManifest);
	return manifest;
}

export async function loadInitialJobsChunk(manifest: SearchManifest) {
	const entity = manifest.entities.jobs;
	const path = entity.initialPath ?? entity.path;
	if (!path) {
		return loadEntityChunk(manifest, "jobs");
	}
	const chunk = await fetchSearchJson<SearchChunk>(path);
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
	const chunk = await fetchSearchJson<SearchChunk>(details.path);
	validateCachedJson(details.path, chunk, (value) => validateSearchChunk(entity, value));
	return chunk;
}

export async function loadLineageAggregate(manifest: SearchManifest) {
	const path = manifest.lineageAggregate?.path ?? LINEAGE_AGGREGATE_PATH;
	const aggregate = await fetchSearchJson<LineageAggregate>(path);
	validateCachedJson(path, aggregate, validateLineageAggregate);
	return aggregate;
}

export async function loadJobsSearchResults(
	filters: JobBoardFilters,
	sortKey: JobSortKey,
	options: { limit?: number; page?: number; pageSize?: number; signal?: AbortSignal } = {},
) {
	const { getJobsSearchWorkerClient } = await import(
		"@/lib/jobs-search-worker-client"
	);
	const payload = await getJobsSearchWorkerClient().search(filters, sortKey, options);
	validateJobsSearchResponse(payload);
	return payload;
}

export async function loadJobsSearchSummary(
	filters: JobBoardFilters,
	sortKey: JobSortKey,
	options: { signal?: AbortSignal } = {},
) {
	const { getJobsSearchWorkerClient } = await import(
		"@/lib/jobs-search-worker-client"
	);
	const payload = await getJobsSearchWorkerClient().summary(filters, sortKey, options);
	validateJobsSearchSummaryResponse(payload);
	return payload;
}

export async function loadSavedSearchCounts(
	searches: SavedSearchCountQuery[],
	options: { signal?: AbortSignal } = {},
) {
	if (searches.length > SAVED_SEARCH_COUNT_BATCH_SIZE) {
		throw new SearchLoadError(
			"invalid_chunk",
			`Saved-search count batches are limited to ${SAVED_SEARCH_COUNT_BATCH_SIZE}.`,
		);
	}
	const { getJobsSearchWorkerClient } = await import(
		"@/lib/jobs-search-worker-client"
	);
	const payload = await getJobsSearchWorkerClient().savedCounts(searches, options);
	validateSavedSearchCountsResponse(payload, searches);
	return payload;
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
		!(response.snapshotAt === null || typeof response.snapshotAt === "string") ||
		typeof response.totalMatches !== "number" ||
		typeof response.sortKey !== "string" ||
		typeof response.filtersHash !== "string"
	) {
		throw new SearchLoadError(
			"invalid_chunk",
			"Jobs search summary response is missing result metadata.",
		);
	}
}

export function validateSavedSearchCountsResponse(
	response: SavedSearchCountsResponse,
	request: SavedSearchCountQuery[],
) {
	if (
		response.entity !== "jobs" ||
		!SUPPORTED_SEARCH_INDEX_VERSIONS.has(response.version) ||
		response.semantics !== "first-seen-v1" ||
		!(response.snapshotAt === null || typeof response.snapshotAt === "string") ||
		!Array.isArray(response.counts) ||
		response.counts.length !== request.length
	) {
		throw new SearchLoadError("invalid_chunk", "Saved-search counts response is invalid.");
	}
	const requestedIds = new Set(request.map((item) => item.id));
	const returnedIds = new Set<string>();
	for (const count of response.counts) {
		if (
			!count ||
			typeof count.id !== "string" ||
			!requestedIds.has(count.id) ||
			returnedIds.has(count.id) ||
			!Number.isInteger(count.totalMatches) ||
			count.totalMatches < 0 ||
			!Number.isInteger(count.newMatches) ||
			count.newMatches < 0 ||
			count.newMatches > count.totalMatches
		) {
			throw new SearchLoadError("invalid_chunk", "Saved-search counts response is invalid.");
		}
		returnedIds.add(count.id);
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
	invalidateBrowserSearchSnapshotRuntime();
	snapshotClientForTests = undefined;
}

/** Rebind future browser reads after the offline cache lifecycle changes. */
export function invalidateBrowserSearchSnapshotRuntime() {
	jsonCache.clear();
	browserSnapshotClient = undefined;
}

export function setSearchSnapshotClientForTests(
	client: OpenOppsSnapshotClient | null,
) {
	snapshotClientForTests = client;
}

/** Resolve the browser's mutable channel once and hand the pinned identity to the worker. */
export async function getBrowserSearchSnapshotDescriptor() {
	const client = getBrowserSnapshotClient();
	if (client) {
		const offline = getJobsOfflineSnapshotConfiguration(client.baseUrl);
		return {
			baseUrl: client.baseUrl.href,
			channel: client.channel,
			releaseId: await client.releaseId(),
			offlineCacheName: offline?.cacheName ?? null,
		};
	}
	const baseUrl =
		typeof window !== "undefined" ? window.location.origin : "http://localhost";
	return { baseUrl, channel: null, releaseId: null, offlineCacheName: null };
}

export async function loadJobsOfflineReleasePlan(signal?: AbortSignal) {
	return getBrowserSnapshotClient()?.getOfflineReleasePlan(signal) ?? null;
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
			const chunk = await fetchSearchJson<SearchChunk>(ref.path);
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

function fetchSearchJson<T>(path: string) {
	const client = getBrowserSnapshotClient();
	return client ? client.getSearchAsset<T>(path) : fetchJson<T>(path);
}

function getBrowserSnapshotClient() {
	if (snapshotClientForTests !== undefined) {
		return snapshotClientForTests;
	}
	if (browserSnapshotClient !== undefined) {
		return browserSnapshotClient;
	}
	const configuredOrigin =
		process.env.NEXT_PUBLIC_OPENOPPS_PUBLIC_DATA_ORIGIN?.trim() ?? "";
	const configuredChannel =
		process.env.NEXT_PUBLIC_OPENOPPS_PUBLIC_DATA_CHANNEL?.trim() ?? "";
	if (!configuredOrigin && !configuredChannel) {
		browserSnapshotClient = null;
		return browserSnapshotClient;
	}
	const runtimeOrigin =
		configuredOrigin ||
		(typeof window !== "undefined" ? window.location.origin : "");
	if (!runtimeOrigin) {
		throw new Error(
			"NEXT_PUBLIC_OPENOPPS_PUBLIC_DATA_ORIGIN is required for v7 snapshot access",
		);
	}
	const offline = getJobsOfflineSnapshotConfiguration(runtimeOrigin);
	browserSnapshotClient = new OpenOppsSnapshotClient({
		baseUrl: runtimeOrigin,
		channel: configuredChannel || null,
		...(offline
			? {
				offlineFallbackReleaseId: offline.releaseId,
				offlineResponseReader: offline.responseReader,
			}
			: {}),
	});
	return browserSnapshotClient;
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
