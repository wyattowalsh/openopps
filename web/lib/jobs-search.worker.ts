import { JobsSearchEngine } from "@/lib/jobs-search-engine-core";
import type {
	JobsSearchWorkerRequest,
	JobsSearchWorkerResponse,
} from "@/lib/jobs-search-worker-protocol";
import { OpenOppsSnapshotClient } from "@/lib/openopps-snapshot-client";
import { createJobsOfflineCacheReader } from "@/lib/jobs-offline-cache";
import { resolveBrowserChunkFetchConcurrency } from "@/lib/chunk-fetch-concurrency";
import {
	validateSearchChunk,
	validateSearchManifest,
} from "@/components/openopps-search/search-index-validation";
import type { SearchChunk } from "@/components/openopps-search/search-types";
import {
	searchRowsFromColumnarChunk,
	type ColumnarJobsChunk,
	validateColumnarJobsChunk,
} from "@/lib/jobs-search-columnar";

type WorkerScope = {
	addEventListener(
		type: "message",
		listener: (event: MessageEvent<JobsSearchWorkerRequest>) => void,
	): void;
	postMessage(message: JobsSearchWorkerResponse): void;
};

const scope = self as unknown as WorkerScope;
const controllers = new Map<number, AbortController>();
let engine: JobsSearchEngine | null = null;

scope.addEventListener("message", (event) => {
	const request = event.data;
	if (request.kind === "cancel") {
		controllers.get(request.requestId)?.abort();
		return;
	}
	void handleRequest(request);
});

async function handleRequest(
	request: Exclude<JobsSearchWorkerRequest, { kind: "cancel" }>,
) {
	const controller = new AbortController();
	controllers.set(request.requestId, controller);
	try {
		switch (request.kind) {
			case "initialize": {
				engine = await initializeEngine(request.snapshot, controller.signal);
				scope.postMessage({
					kind: "initialized",
					requestId: request.requestId,
					stats: engine.stats(),
				});
				break;
			}
			case "search": {
				const activeEngine = requireEngine();
				const result = await activeEngine.searchCooperative({
					filters: request.filters,
					sortKey: request.sortKey,
					limit: request.limit,
					page: request.page,
					pageSize: request.pageSize,
					signal: controller.signal,
				});
				scope.postMessage({
					kind: "search-result",
					requestId: request.requestId,
					result,
				});
				break;
			}
			case "summary": {
				const result = await requireEngine().summaryCooperative(
					request.filters,
					request.sortKey,
					controller.signal,
				);
				scope.postMessage({
					kind: "summary-result",
					requestId: request.requestId,
					result,
				});
				break;
			}
			case "saved-counts": {
				const result = await requireEngine().countSavedSearchesCooperative(
					request.searches,
					controller.signal,
				);
				scope.postMessage({
					kind: "saved-counts-result",
					requestId: request.requestId,
					result,
				});
				break;
			}
		}
	} catch (caught) {
		const error = caught instanceof Error ? caught : new Error(String(caught));
		scope.postMessage({
			kind: "error",
			requestId: request.requestId,
			name: error.name,
			message: error.message,
		});
	} finally {
		controllers.delete(request.requestId);
	}
}

async function initializeEngine(
	snapshot: import("@/lib/jobs-search-worker-protocol").JobsSearchSnapshotDescriptor,
	signal: AbortSignal,
) {
	const client = new OpenOppsSnapshotClient({
		baseUrl: snapshot.baseUrl,
		channel: snapshot.channel,
		pinnedReleaseId: snapshot.releaseId,
		...(snapshot.offlineCacheName && typeof globalThis.caches !== "undefined"
			? {
				offlineResponseReader: createJobsOfflineCacheReader(
					snapshot.offlineCacheName,
					globalThis.caches,
				),
			}
			: {}),
	});
	const resolvedReleaseId = await client.releaseId(signal);
	if (resolvedReleaseId !== snapshot.releaseId) {
		throw new Error(
			"The pinned public-data release identity failed validation.",
		);
	}
	const manifest = await client.getSearchManifest(signal);
	validateSearchManifest(manifest);
	const jobs = manifest.entities.jobs;
	if (
		typeof snapshot.bootstrapJobsCount === "number" &&
		snapshot.bootstrapJobsCount !== jobs.count
	) {
		throw new Error(
			`Jobs search bootstrap count mismatch: chrome ${snapshot.bootstrapJobsCount}, manifest ${jobs.count}.`,
		);
	}
	const columnarRefs = jobs.columnar?.chunks?.length
		? [...jobs.columnar.chunks].sort((left, right) => left.index - right.index)
		: [];
	if (columnarRefs.length > 0) {
		const chunks = await loadColumnarChunks(client, columnarRefs, signal);
		const rows = chunks.flatMap((chunk) => searchRowsFromColumnarChunk(chunk));
		if (rows.length !== jobs.count) {
			throw new Error(
				`Jobs search row count mismatch: expected ${jobs.count}, received ${rows.length}.`,
			);
		}
		return new JobsSearchEngine({ manifest, rows });
	}
	const refs = jobs.chunks?.length
		? [...jobs.chunks].sort((left, right) => left.index - right.index)
		: jobs.path
			? [{ index: 0, path: jobs.path }]
			: [];
	if (refs.length === 0) {
		throw new Error("Search manifest is missing jobs entity chunks.");
	}
	const chunks = await loadChunks(client, refs, signal);
	const rows = chunks.flatMap((chunk) => chunk.rows);
	if (rows.length !== jobs.count) {
		throw new Error(
			`Jobs search row count mismatch: expected ${jobs.count}, received ${rows.length}.`,
		);
	}
	return new JobsSearchEngine({ manifest, rows });
}

async function loadChunks(
	client: OpenOppsSnapshotClient,
	refs: Array<{ path: string }>,
	signal: AbortSignal,
) {
	const chunks: SearchChunk[] = new Array(refs.length);
	let cursor = 0;
	async function fetchNext() {
		while (cursor < refs.length) {
			if (signal.aborted) {
				throw new DOMException("The operation was aborted.", "AbortError");
			}
			const index = cursor;
			cursor += 1;
			const chunk = await client.getSearchChunk(refs[index].path, signal);
			validateSearchChunk("jobs", chunk);
			chunks[index] = chunk;
		}
	}
	const pool = Math.min(resolveBrowserChunkFetchConcurrency(), refs.length);
	await Promise.all(
		Array.from({ length: pool }, () => fetchNext()),
	);
	return chunks;
}

async function loadColumnarChunks(
	client: OpenOppsSnapshotClient,
	refs: Array<{ path: string }>,
	signal: AbortSignal,
) {
	const chunks: ColumnarJobsChunk[] = new Array(refs.length);
	let cursor = 0;
	async function fetchNext() {
		while (cursor < refs.length) {
			if (signal.aborted) {
				throw new DOMException("The operation was aborted.", "AbortError");
			}
			const index = cursor;
			cursor += 1;
			const chunk = await client.getColumnarJobsChunk(refs[index].path, signal);
			validateColumnarJobsChunk(chunk);
			chunks[index] = chunk;
		}
	}
	const pool = Math.min(resolveBrowserChunkFetchConcurrency(), refs.length);
	await Promise.all(Array.from({ length: pool }, () => fetchNext()));
	return chunks;
}

function requireEngine() {
	if (!engine) {
		throw new Error("Jobs search worker is not initialized.");
	}
	return engine;
}
