"use client";

import type {
	JobBoardFilters,
	JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import type {
	JobsSearchResponse,
	JobsSearchSummaryResponse,
	SavedSearchCountQuery,
	SavedSearchCountsResponse,
} from "@/components/openopps-search/search-types";
import type {
	JobsSearchSnapshotDescriptor,
	JobsSearchWorkerRequest,
	JobsSearchWorkerResponse,
} from "@/lib/jobs-search-worker-protocol";

type WorkerLike = Pick<
	Worker,
	"postMessage" | "terminate" | "addEventListener" | "removeEventListener"
>;

type WorkerFactory = () => WorkerLike;
type SnapshotLoader = () => Promise<JobsSearchSnapshotDescriptor>;
type WithoutRequestId<T> = T extends unknown ? Omit<T, "requestId"> : never;
type JobsSearchWorkerCommand = WithoutRequestId<
	Exclude<JobsSearchWorkerRequest, { kind: "cancel" }>
>;

type PendingRequest = {
	resolve: (value: JobsSearchWorkerResponse) => void;
	reject: (reason: unknown) => void;
	cleanup: () => void;
};

export class JobsSearchWorkerClient {
	private readonly worker: WorkerLike;
	private readonly snapshotLoader: SnapshotLoader;
	private readonly pending = new Map<number, PendingRequest>();
	private requestSequence = 0;
	private initializePromise: Promise<void> | null = null;

	constructor(options: {
		workerFactory?: WorkerFactory;
		snapshotLoader?: SnapshotLoader;
	} = {}) {
		this.worker = (options.workerFactory ?? defaultWorkerFactory)();
		this.snapshotLoader = options.snapshotLoader ?? loadBrowserSnapshotDescriptor;
		this.worker.addEventListener("message", this.handleMessage);
		this.worker.addEventListener("error", this.handleWorkerError);
	}

	async search(
		filters: JobBoardFilters,
		sortKey: JobSortKey,
		options: { limit?: number; page?: number; pageSize?: number; signal?: AbortSignal } = {},
	): Promise<JobsSearchResponse> {
		await awaitWithAbort(this.initialize(), options.signal);
		const response = await this.request(
			{
				kind: "search",
				filters,
				sortKey,
				limit: options.limit,
				page: options.page,
				pageSize: options.pageSize,
			},
			options.signal,
		);
		if (response.kind !== "search-result") {
			throw new Error("Jobs search worker returned an unexpected response.");
		}
		return response.result;
	}

	async summary(
		filters: JobBoardFilters,
		sortKey: JobSortKey,
		options: { signal?: AbortSignal } = {},
	): Promise<JobsSearchSummaryResponse> {
		await awaitWithAbort(this.initialize(), options.signal);
		const response = await this.request(
			{ kind: "summary", filters, sortKey },
			options.signal,
		);
		if (response.kind !== "summary-result") {
			throw new Error("Jobs search worker returned an unexpected response.");
		}
		return response.result;
	}

	async savedCounts(
		searches: SavedSearchCountQuery[],
		options: { signal?: AbortSignal } = {},
	): Promise<SavedSearchCountsResponse> {
		await awaitWithAbort(this.initialize(), options.signal);
		const response = await this.request(
			{ kind: "saved-counts", searches },
			options.signal,
		);
		if (response.kind !== "saved-counts-result") {
			throw new Error("Jobs search worker returned an unexpected response.");
		}
		return response.result;
	}

	dispose() {
		this.worker.removeEventListener("message", this.handleMessage);
		this.worker.removeEventListener("error", this.handleWorkerError);
		this.worker.terminate();
		this.rejectAll(new Error("Jobs search worker was disposed."));
	}

	private initialize() {
		if (!this.initializePromise) {
			this.initializePromise = this.snapshotLoader()
				.then((snapshot) => this.request({ kind: "initialize", snapshot }))
				.then((response) => {
					if (response.kind !== "initialized") {
						throw new Error("Jobs search worker failed to initialize.");
					}
				})
				.catch((caught: unknown) => {
					this.initializePromise = null;
					throw caught;
				});
		}
		return this.initializePromise;
	}

	private request(
		request: JobsSearchWorkerCommand,
		signal?: AbortSignal,
	) {
		if (signal?.aborted) {
			return Promise.reject(abortError());
		}
		const requestId = this.requestSequence + 1;
		this.requestSequence = requestId;
		return new Promise<JobsSearchWorkerResponse>((resolve, reject) => {
			const abort = () => {
				this.worker.postMessage({ kind: "cancel", requestId } satisfies JobsSearchWorkerRequest);
				this.pending.delete(requestId);
				signal?.removeEventListener("abort", abort);
				reject(abortError());
			};
			this.pending.set(requestId, {
				resolve,
				reject,
				cleanup: () => signal?.removeEventListener("abort", abort),
			});
			signal?.addEventListener("abort", abort, { once: true });
			this.worker.postMessage({ ...request, requestId } as JobsSearchWorkerRequest);
		});
	}

	private readonly handleMessage = (event: MessageEvent<JobsSearchWorkerResponse>) => {
		const response = event.data;
		const pending = this.pending.get(response.requestId);
		if (!pending) {
			return;
		}
		this.pending.delete(response.requestId);
		pending.cleanup();
		if (response.kind === "error") {
			const error = new Error(response.message);
			error.name = response.name;
			pending.reject(error);
			return;
		}
		pending.resolve(response);
	};

	private readonly handleWorkerError = (event: ErrorEvent) => {
		this.initializePromise = null;
		this.rejectAll(event.error ?? new Error(event.message || "Jobs search worker failed."));
	};

	private rejectAll(reason: unknown) {
		for (const pending of this.pending.values()) {
			pending.cleanup();
			pending.reject(reason);
		}
		this.pending.clear();
	}
}

let singleton: JobsSearchWorkerClient | null = null;
let overrideForTests: JobsSearchWorkerClient | null | undefined;

export function getJobsSearchWorkerClient() {
	if (overrideForTests !== undefined) {
		if (!overrideForTests) {
			throw new Error("Jobs search worker is disabled for this test.");
		}
		return overrideForTests;
	}
	if (!singleton) {
		singleton = new JobsSearchWorkerClient();
	}
	return singleton;
}

export function setJobsSearchWorkerClientForTests(
	client: JobsSearchWorkerClient | null | undefined,
) {
	overrideForTests = client;
}

export function clearJobsSearchWorkerClientForTests() {
	resetJobsSearchWorkerRuntime();
	overrideForTests = undefined;
}

/** Recreate the worker against the current release/offline-cache configuration. */
export function resetJobsSearchWorkerRuntime() {
	singleton?.dispose();
	singleton = null;
}

function defaultWorkerFactory() {
	return new Worker(new URL("./jobs-search.worker.ts", import.meta.url), {
		type: "module",
		name: "openopps-jobs-search",
	});
}

async function loadBrowserSnapshotDescriptor() {
	const { getBrowserSearchSnapshotDescriptor } = await import(
		"@/components/openopps-search/search-index-loader"
	);
	return getBrowserSearchSnapshotDescriptor();
}

function awaitWithAbort<T>(promise: Promise<T>, signal?: AbortSignal) {
	if (!signal) {
		return promise;
	}
	if (signal.aborted) {
		return Promise.reject(abortError());
	}
	return new Promise<T>((resolve, reject) => {
		const abort = () => reject(abortError());
		signal.addEventListener("abort", abort, { once: true });
		promise.then(
			(value) => {
				signal.removeEventListener("abort", abort);
				resolve(value);
			},
			(caught) => {
				signal.removeEventListener("abort", abort);
				reject(caught);
			},
		);
	});
}

function abortError() {
	return new DOMException("The operation was aborted.", "AbortError");
}
