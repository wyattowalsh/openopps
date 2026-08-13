import type {
	Entity,
	SearchChunk,
	SearchManifest,
} from "@/components/openopps-search/search-types";
import {
	EXPECTED_COLUMNS,
	SEARCH_VERSION,
	SearchLoadError,
	expectedColumnsFor,
} from "@/components/openopps-search/search-utils";

const SUPPORTED_SEARCH_INDEX_VERSIONS = new Set([3, SEARCH_VERSION]);

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
