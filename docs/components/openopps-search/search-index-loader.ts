import type {
	Entity,
	SearchChunk,
	SearchChunkRef,
	SearchManifest,
	SearchRow,
} from "./search-types";
import { EXPECTED_COLUMNS, SEARCH_VERSION } from "./search-utils";

export const SEARCH_MANIFEST_PATH = "/data/openopps-search/manifest.json";
const MAX_CHUNK_FETCHES = 6;

const jsonCache = new Map<string, Promise<unknown>>();

export async function fetchJson<T>(path: string): Promise<T> {
	let cached = jsonCache.get(path);
	if (!cached) {
		cached = fetch(path, { cache: "force-cache" }).then(async (response) => {
			if (!response.ok) {
				throw new Error(`Unable to load ${path}: ${response.status}`);
			}
			return response.json() as Promise<unknown>;
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
			version: SEARCH_VERSION,
			entity,
			columns: details.columns,
			count: rows.length,
			rows,
		} satisfies SearchChunk;
	}
	if (!details.path) {
		throw new Error(`Search manifest is missing ${entity} entity path.`);
	}
	const chunk = await fetchJson<SearchChunk>(details.path);
	validateSearchChunk(entity, chunk);
	return chunk;
}

export function validateSearchManifest(manifest: SearchManifest) {
	if (manifest.version !== SEARCH_VERSION) {
		throw new Error(`Unsupported search index version: ${manifest.version}`);
	}
	for (const entity of Object.keys(EXPECTED_COLUMNS) as Entity[]) {
		const columns = manifest.entities?.[entity]?.columns;
		if (!columns || columns.join("\0") !== EXPECTED_COLUMNS[entity].join("\0")) {
			throw new Error(`Search index manifest columns do not match ${entity}`);
		}
	}
}

export function validateSearchChunk(entity: Entity, chunk: SearchChunk) {
	if (chunk.version !== SEARCH_VERSION || chunk.entity !== entity) {
		throw new Error(`Unsupported ${entity} search index chunk`);
	}
	if (chunk.columns.join("\0") !== EXPECTED_COLUMNS[entity].join("\0")) {
		throw new Error(`Search index chunk columns do not match ${entity}`);
	}
	if (chunk.count !== chunk.rows.length) {
		throw new Error(`Search index chunk count does not match ${entity} rows`);
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
