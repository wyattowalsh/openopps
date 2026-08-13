// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useJobsLocalState } from "@/components/jobs-board/jobs-board-local-hook";
import {
	createJobsLocalExportEnvelope,
	updateJobWorkflowRecord,
} from "@/components/jobs-board/jobs-board-local-reconcile";
import { DEFAULT_JOBS_LOCAL_SETTINGS } from "@/components/jobs-board/jobs-board-local-types";
import type { SearchManifest } from "@/components/openopps-search/search-types";

const idbMocks = vi.hoisted(() => ({
	clearIndexedJobsLocalData: vi.fn(),
	hasBrowserIndexedDb: vi.fn(() => true),
	readIndexedJobsLocalSnapshot: vi.fn(),
	importIndexedSnapshot: vi.fn(),
	replaceIndexedSnapshot: vi.fn(),
	writeJobWorkflowTransaction: vi.fn(),
}));

vi.mock("@/components/jobs-board/jobs-board-local-idb", async (importOriginal) => {
	const actual = await importOriginal<
		typeof import("@/components/jobs-board/jobs-board-local-idb")
	>();
	return {
		...actual,
		...idbMocks,
	};
});

beforeEach(() => {
	const localValues = new Map<string, string>();
	Object.defineProperty(window, "localStorage", {
		configurable: true,
		value: {
			clear: () => localValues.clear(),
			getItem: (key: string) => localValues.get(key) ?? null,
			removeItem: (key: string) => localValues.delete(key),
			setItem: (key: string, value: string) => localValues.set(key, value),
		},
	});
	idbMocks.hasBrowserIndexedDb.mockReturnValue(true);
	idbMocks.readIndexedJobsLocalSnapshot.mockResolvedValue({
		jobRecords: [],
		savedSearches: [],
		retainedJobDetails: [],
	});
	idbMocks.writeJobWorkflowTransaction.mockReset();
	idbMocks.clearIndexedJobsLocalData.mockReset().mockResolvedValue(undefined);
	idbMocks.importIndexedSnapshot.mockReset().mockResolvedValue(undefined);
	idbMocks.replaceIndexedSnapshot.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe("useJobsLocalState durable mutation ordering", () => {
	it("does not publish a local job mutation until its durable write commits", async () => {
		const committed = deferred<void>();
		idbMocks.writeJobWorkflowTransaction.mockReturnValueOnce(committed.promise);
		const { result } = renderHook(() => useJobsLocalState(), {
			wrapper: StrictMode,
		});
		await waitFor(() => expect(result.current.storageStatus).toBe("available"));

		act(() => result.current.updateNotes("job-a", "durable note"));
		await waitFor(() =>
			expect(idbMocks.writeJobWorkflowTransaction).toHaveBeenCalledTimes(1),
		);
		expect(result.current.jobRecords["job-a"]).toBeUndefined();

		await act(async () => committed.resolve());
		await waitFor(() =>
			expect(result.current.jobRecords["job-a"]?.notes).toBe("durable note"),
		);
	});

	it("serializes rapid state changes and preserves their call order", async () => {
		const first = deferred<void>();
		const second = deferred<void>();
		idbMocks.writeJobWorkflowTransaction
			.mockReturnValueOnce(first.promise)
			.mockReturnValueOnce(second.promise);
		const { result } = renderHook(() => useJobsLocalState());
		await waitFor(() => expect(result.current.storageStatus).toBe("available"));

		act(() => {
			result.current.updateNotes("job-a", "first");
			result.current.updateNotes("job-a", "second");
		});
		await waitFor(() =>
			expect(idbMocks.writeJobWorkflowTransaction).toHaveBeenCalledTimes(1),
		);
		expect(result.current.jobRecords["job-a"]).toBeUndefined();

		await act(async () => first.resolve());
		await waitFor(() =>
			expect(idbMocks.writeJobWorkflowTransaction).toHaveBeenCalledTimes(2),
		);
		expect(result.current.jobRecords["job-a"]?.notes).toBe("first");
		expect(
			idbMocks.writeJobWorkflowTransaction.mock.calls.map(
				([input]) => input.record.notes,
			),
		).toEqual(["first", "second"]);

		await act(async () => second.resolve());
		await waitFor(() =>
			expect(result.current.jobRecords["job-a"]?.notes).toBe("second"),
		);
	});

	it("preserves visible state and exposes a handled durable-write error", async () => {
		idbMocks.writeJobWorkflowTransaction.mockRejectedValueOnce(
			new Error("Quota exceeded while saving local job data."),
		);
		const { result } = renderHook(() => useJobsLocalState());
		await waitFor(() => expect(result.current.storageStatus).toBe("available"));

		act(() => result.current.updateNotes("job-a", "must not appear"));

		await waitFor(() => expect(result.current.storageStatus).toBe("error"));
		expect(result.current.storageError).toBe(
			"Quota exceeded while saving local job data.",
		);
		expect(result.current.jobRecords["job-a"]).toBeUndefined();
	});

	it("keeps the committed snapshot authoritative when a transactional clear fails", async () => {
		idbMocks.writeJobWorkflowTransaction.mockResolvedValueOnce(undefined);
		const { result } = renderHook(() => useJobsLocalState());
		await waitFor(() => expect(result.current.storageStatus).toBe("available"));
		act(() => result.current.updateNotes("job-a", "keep this note"));
		await waitFor(() =>
			expect(result.current.jobRecords["job-a"]?.notes).toBe("keep this note"),
		);
		idbMocks.replaceIndexedSnapshot.mockRejectedValueOnce(
			new Error("Clear transaction aborted."),
		);

		await act(async () => result.current.clearCategory("notes"));

		expect(result.current.storageError).toBe("Clear transaction aborted.");
		expect(result.current.jobRecords["job-a"]?.notes).toBe("keep this note");
	});

	it("keeps visible data unchanged when an import transaction fails", async () => {
		idbMocks.writeJobWorkflowTransaction.mockResolvedValueOnce(undefined);
		const { result } = renderHook(() => useJobsLocalState());
		await waitFor(() => expect(result.current.storageStatus).toBe("available"));
		act(() => result.current.updateNotes("job-a", "current note"));
		await waitFor(() =>
			expect(result.current.jobRecords["job-a"]?.notes).toBe("current note"),
		);
		idbMocks.importIndexedSnapshot.mockRejectedValueOnce(
			new Error("Import transaction aborted."),
		);
		const imported = createJobsLocalExportEnvelope({
			settings: { ...DEFAULT_JOBS_LOCAL_SETTINGS, showHidden: true },
			jobRecords: [
				updateJobWorkflowRecord(
					null,
					{ notes: "replacement" },
					{ jobId: "job-b", now: "2026-08-12T10:00:00.000Z" },
				),
			],
			savedSearches: [],
			retainedJobDetails: [],
		});

		const importResult = await act(async () =>
			result.current.importLocalData(JSON.stringify(imported), "replace"),
		);

		expect(importResult).toMatchObject({
			ok: false,
			errors: ["Import transaction aborted."],
		});
		expect(result.current.jobRecords["job-a"]?.notes).toBe("current note");
		expect(result.current.jobRecords["job-b"]).toBeUndefined();
		expect(result.current.settings.showHidden).toBe(false);
	});

	it("does not publish reconciliation state when its replace transaction aborts", async () => {
		idbMocks.writeJobWorkflowTransaction.mockResolvedValueOnce(undefined);
		const { result } = renderHook(() => useJobsLocalState());
		await waitFor(() => expect(result.current.storageStatus).toBe("available"));
		act(() => result.current.updateNotes("job-a", "durable note"));
		await waitFor(() =>
			expect(result.current.jobRecords["job-a"]?.notes).toBe("durable note"),
		);
		idbMocks.replaceIndexedSnapshot.mockRejectedValueOnce(
			new Error("Reconciliation transaction aborted."),
		);

		const reconciled = await act(async () =>
			result.current.reconcileSnapshot([], manifest(), true),
		);

		expect(reconciled).toBe(false);
		expect(result.current.storageError).toBe(
			"Reconciliation transaction aborted.",
		);
		expect(result.current.jobRecords["job-a"]?.firstAbsentSnapshotAt).toBeNull();
	});
});

function manifest(): SearchManifest {
	return {
		version: 6,
		snapshotAt: "2026-08-12T00:00:00.000Z",
		source: { database: "openopps.sqlite", tables: [] },
		defaultEntity: "jobs",
		defaultFilters: { jobs: { status: "open" } },
		entities: {
			jobs: { columns: [], count: 0 },
			boards: { columns: [], count: 0 },
			providers: { columns: [], count: 0 },
		},
		facets: {
			sources: [],
			providerIds: [],
			jobStatuses: [],
			supportLevels: [],
			routeStatuses: [],
			workplaces: [],
			employmentTypes: [],
		},
	};
}

function deferred<T>() {
	let resolve!: (value: T | PromiseLike<T>) => void;
	let reject!: (reason?: unknown) => void;
	const promise = new Promise<T>((resolvePromise, rejectPromise) => {
		resolve = resolvePromise;
		reject = rejectPromise;
	});
	return { promise, resolve, reject };
}
