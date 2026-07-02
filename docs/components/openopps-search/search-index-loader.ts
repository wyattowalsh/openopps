import type {
	Entity,
	SearchChunk,
	SearchChunkRef,
	SearchManifest,
	SearchRow,
} from "./search-types";
import {
	EXPECTED_COLUMNS,
	SEARCH_VERSION,
	SearchLoadError,
	expectedColumnsFor,
} from "./search-utils";

export const SEARCH_MANIFEST_PATH = "/data/openopps-search/manifest.json";
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
	validateSearchManifest(manifest);
	return manifest;
}

export async function loadInitialJobsChunk(manifest: SearchManifest) {
	const entity = manifest.entities.jobs;
	const path = entity.initialPath ?? entity.path;
	if (!path) {
		return loadEntityChunk(manifest, "jobs");
	}
	const chunk = await fetchJson<SearchChunk>(path);
	validateSearchChunk("jobs", chunk);
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
	validateSearchChunk(entity, chunk);
	return chunk;
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
			const chunk = await fetchJson<SearchChunk>(orderedRefs[index].path);
			validateSearchChunk(entity, chunk);
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
