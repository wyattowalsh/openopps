import { afterEach, describe, expect, it, vi } from "vitest";

import {
	DEFAULT_JOB_BOARD_FILTERS,
} from "@/components/jobs-board/jobs-board-filter-engine";
import {
	JobsSearchWorkerClient,
	clearJobsSearchWorkerClientForTests,
} from "@/lib/jobs-search-worker-client";
import type {
	JobsSearchWorkerRequest,
	JobsSearchWorkerResponse,
} from "@/lib/jobs-search-worker-protocol";

afterEach(() => {
	clearJobsSearchWorkerClientForTests();
	vi.restoreAllMocks();
});

describe("JobsSearchWorkerClient", () => {
	it("initializes once and reuses a release-pinned worker", async () => {
		const worker = new FakeWorker();
		const client = new JobsSearchWorkerClient({
			workerFactory: () => worker,
			snapshotLoader: vi.fn().mockResolvedValue({
				baseUrl: "https://data.example/",
				channel: "production",
				releaseId: "a".repeat(64),
			}),
		});
		const first = client.search(DEFAULT_JOB_BOARD_FILTERS, "latest", { page: 1 });
		const second = client.summary(DEFAULT_JOB_BOARD_FILTERS, "latest");

		await vi.waitFor(() => expect(worker.requests).toHaveLength(1));
		expect(worker.requests[0]).toMatchObject({
			kind: "initialize",
			snapshot: { releaseId: "a".repeat(64) },
		});
		worker.respond({
			kind: "initialized",
			requestId: worker.requests[0].requestId,
			stats: workerStats({ rows: 10, indexBytes: 64, dictionaryValues: 5 }),
		});
		await vi.waitFor(() => expect(worker.requests).toHaveLength(3));
		const search = worker.requests.find((request) => request.kind === "search");
		const summary = worker.requests.find((request) => request.kind === "summary");
		if (!search || !summary) {
			throw new Error("Expected search and summary worker requests.");
		}
		worker.respond({
			kind: "search-result",
			requestId: search.requestId,
			result: {
				version: 6,
				entity: "jobs",
				columns: [],
				count: 0,
				rows: [],
				totalMatches: 0,
				limit: 50,
				page: 1,
				pageSize: 50,
				totalPages: 1,
				hasNextPage: false,
				hasPreviousPage: false,
				truncated: false,
			},
		});
		worker.respond({
			kind: "summary-result",
			requestId: summary.requestId,
			result: {
				version: 6,
				entity: "jobs",
				snapshotAt: "2026-01-01T00:00:00Z",
				totalMatches: 0,
				sortKey: "latest",
				filtersHash: "{}",
			},
		});

		await expect(first).resolves.toMatchObject({ totalMatches: 0 });
		await expect(second).resolves.toMatchObject({ totalMatches: 0 });
		expect(worker.requests.filter((request) => request.kind === "initialize")).toHaveLength(1);
		client.dispose();
	});

	it("cancels only the aborted request and ignores its late response", async () => {
		const worker = new FakeWorker();
		const client = new JobsSearchWorkerClient({
			workerFactory: () => worker,
			snapshotLoader: vi.fn().mockResolvedValue({
				baseUrl: "https://data.example/",
				channel: null,
				releaseId: null,
			}),
		});
		const controller = new AbortController();
		const search = client.search(DEFAULT_JOB_BOARD_FILTERS, "latest", {
			signal: controller.signal,
		});
		await vi.waitFor(() => expect(worker.requests).toHaveLength(1));
		worker.respond({
			kind: "initialized",
			requestId: worker.requests[0].requestId,
			stats: workerStats({ rows: 1, indexBytes: 8, dictionaryValues: 1 }),
		});
		await vi.waitFor(() =>
			expect(worker.requests.some((request) => request.kind === "search")).toBe(true),
		);
		const request = worker.requests.find((candidate) => candidate.kind === "search");
		if (!request) {
			throw new Error("Expected a search worker request.");
		}
		controller.abort();

		await expect(search).rejects.toMatchObject({ name: "AbortError" });
		expect(worker.requests).toContainEqual({
			kind: "cancel",
			requestId: request.requestId,
		});
		worker.respond({
			kind: "error",
			requestId: request.requestId,
			name: "AbortError",
			message: "late",
		});
		client.dispose();
	});

	it("rejects one worker error without stranding later requests", async () => {
		const worker = new FakeWorker();
		const client = new JobsSearchWorkerClient({
			workerFactory: () => worker,
			snapshotLoader: vi.fn().mockResolvedValue({
				baseUrl: "https://data.example/",
				channel: null,
				releaseId: null,
			}),
		});
		const first = client.summary(DEFAULT_JOB_BOARD_FILTERS, "latest");
		await vi.waitFor(() => expect(worker.requests).toHaveLength(1));
		worker.respond({
			kind: "initialized",
			requestId: worker.requests[0].requestId,
			stats: workerStats({ rows: 1, indexBytes: 8, dictionaryValues: 1 }),
		});
		await vi.waitFor(() => expect(worker.requests).toHaveLength(2));
		worker.respond({
			kind: "error",
			requestId: worker.requests[1].requestId,
			name: "SearchLoadError",
			message: "bad snapshot",
		});
		await expect(first).rejects.toMatchObject({ message: "bad snapshot" });

		const second = client.summary(DEFAULT_JOB_BOARD_FILTERS, "latest");
		await vi.waitFor(() => expect(worker.requests).toHaveLength(3));
		worker.respond({
			kind: "summary-result",
			requestId: worker.requests[2].requestId,
			result: {
				version: 6,
				entity: "jobs",
				snapshotAt: null,
				totalMatches: 4,
				sortKey: "latest",
				filtersHash: "{}",
			},
		});
		await expect(second).resolves.toMatchObject({ totalMatches: 4 });
		client.dispose();
	});
});

class FakeWorker {
	readonly requests: JobsSearchWorkerRequest[] = [];
	private readonly messageListeners = new Set<
		(event: MessageEvent<JobsSearchWorkerResponse>) => void
	>();
	private readonly errorListeners = new Set<(event: ErrorEvent) => void>();

	postMessage = (request: JobsSearchWorkerRequest) => {
		this.requests.push(request);
	};

	terminate = vi.fn();

	addEventListener = (
		type: string,
		listener: EventListenerOrEventListenerObject,
	) => {
		if (typeof listener !== "function") {
			return;
		}
		if (type === "message") {
			this.messageListeners.add(
				listener as (event: MessageEvent<JobsSearchWorkerResponse>) => void,
			);
		} else if (type === "error") {
			this.errorListeners.add(listener as (event: ErrorEvent) => void);
		}
	};

	removeEventListener = (
		type: string,
		listener: EventListenerOrEventListenerObject,
	) => {
		if (typeof listener !== "function") {
			return;
		}
		if (type === "message") {
			this.messageListeners.delete(
				listener as (event: MessageEvent<JobsSearchWorkerResponse>) => void,
			);
		} else if (type === "error") {
			this.errorListeners.delete(listener as (event: ErrorEvent) => void);
		}
	};

	respond(response: JobsSearchWorkerResponse) {
		const event = { data: response } as MessageEvent<JobsSearchWorkerResponse>;
		for (const listener of this.messageListeners) {
			listener(event);
		}
	}
}

function workerStats(base: {
	rows: number;
	indexBytes: number;
	dictionaryValues: number;
}) {
	return {
		...base,
		cachedResults: 0,
		cachedRowReferences: 0,
		maxCachedRowReferences: 250_000,
	};
}
