import { readFile } from "node:fs/promises";
import { resolve, sep } from "node:path";
import { gzipSync } from "node:zlib";

import type {
	SearchChunk,
	SearchManifest,
	SearchRow,
} from "../components/openopps-search/search-types";
import {
	validateSearchChunk,
	validateSearchManifest,
} from "../components/openopps-search/search-index-validation";
import {
	JobsSearchEngine,
	MAX_FILTER_RESULT_CACHE_ROW_REFERENCES,
} from "../lib/jobs-search-engine-core";

async function main() {
	const root = resolve(process.argv[2] ?? "public/data/openopps-search");
	const manifestRaw = await readFile(resolve(root, "manifest.json"));
	const manifest = JSON.parse(manifestRaw.toString("utf8")) as SearchManifest;
	validateSearchManifest(manifest);

	const refs = manifest.entities.jobs.chunks?.length
		? [...manifest.entities.jobs.chunks].sort((left, right) => left.index - right.index)
		: [];
	if (refs.length === 0) {
		throw new Error("Production search manifest has no jobs chunks.");
	}

	const rows: SearchRow[] = [];
	let rawChunkBytes = 0;
	let gzipChunkBytes = 0;
	for (const ref of refs) {
		const path = resolve(root, ref.file);
		if (!path.startsWith(`${root}${sep}`)) {
			throw new Error(`Unsafe jobs chunk path: ${ref.file}`);
		}
		const raw = await readFile(path);
		rawChunkBytes += raw.byteLength;
		gzipChunkBytes += gzipSync(raw, { level: 9 }).byteLength;
		const chunk = JSON.parse(raw.toString("utf8")) as SearchChunk;
		validateSearchChunk("jobs", chunk);
		rows.push(...chunk.rows);
	}
	if (rows.length !== manifest.entities.jobs.count) {
		throw new Error(
			`Production jobs count mismatch: ${rows.length} != ${manifest.entities.jobs.count}`,
		);
	}

	const beforeHeap = process.memoryUsage().heapUsed;
	const engine = new JobsSearchEngine({ manifest, rows });
	const afterHeap = process.memoryUsage().heapUsed;
	const stats = engine.stats();

	process.stdout.write(
		`${JSON.stringify(
		{
			schemaVersion: 1,
			corpus: {
				manifest: "public/data/openopps-search/manifest.json",
				snapshotAt: manifest.snapshotAt,
				rows: rows.length,
				chunks: refs.length,
			},
			transferProxy: {
				rawChunkBytes,
				gzipLevel9ChunkBytes: gzipChunkBytes,
			},
			heapProxy: {
				serializedRowEnvelopeBytes: rawChunkBytes,
				typedPostingIndexBytes: stats.indexBytes,
				observedIndexBuildHeapDeltaBytes: afterHeap - beforeHeap,
				observedHeapCaveat:
					"Node heap deltas are GC/runtime/load dependent and are not a browser guarantee.",
				maxCachedRowReferences: MAX_FILTER_RESULT_CACHE_ROW_REFERENCES,
				maxCachedReferenceBytesAtEightBytesEach:
					MAX_FILTER_RESULT_CACHE_ROW_REFERENCES * 8,
			},
		},
		null,
		2,
		)}\n`,
	);
}

void main();
