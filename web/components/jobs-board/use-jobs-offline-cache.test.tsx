// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useJobsOfflineCache } from "./use-jobs-offline-cache";

const mocks = vi.hoisted(() => ({
	disable: vi.fn(),
	invalidateSnapshot: vi.fn(),
	loadPlan: vi.fn(),
	prepare: vi.fn(),
	ready: null as typeof receipt | null,
	resetWorker: vi.fn(),
	optedIn: false,
	verify: vi.fn(),
}));

vi.mock("@/components/openopps-search/search-index-loader", () => ({
	invalidateBrowserSearchSnapshotRuntime: mocks.invalidateSnapshot,
	loadJobsOfflineReleasePlan: mocks.loadPlan,
}));

vi.mock("@/lib/jobs-search-worker-client", () => ({
	resetJobsSearchWorkerRuntime: mocks.resetWorker,
}));

vi.mock("@/lib/jobs-offline-cache", async (importOriginal) => {
	const actual = await importOriginal<
		typeof import("@/lib/jobs-offline-cache")
	>();
	return {
		...actual,
		disableJobsOfflineCache: mocks.disable,
		isJobsOfflineOptedIn: () => mocks.optedIn,
		prepareJobsOfflineCache: mocks.prepare,
		readJobsOfflineReady: () => mocks.ready,
		setJobsOfflineOptIn: vi.fn(),
		verifyOrDiscardJobsOfflineCache: mocks.verify,
	};
});

const releaseId = "a".repeat(64);
const plan = { releaseId };
const receipt = {
	schemaVersion: 1,
	releaseId,
	cacheName: `openopps-jobs-offline-v1:${releaseId}:token`,
	fileCount: 1,
	totalBytes: 10,
	verifiedAt: "2026-08-12T00:00:00.000Z",
};

beforeEach(() => {
	mocks.loadPlan.mockResolvedValue(plan);
	mocks.prepare.mockResolvedValue(receipt);
	mocks.disable.mockResolvedValue(undefined);
	mocks.verify.mockResolvedValue(undefined);
	mocks.ready = null;
	mocks.optedIn = false;
});

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe("useJobsOfflineCache runtime lifecycle", () => {
	it("rebinds the snapshot client and worker after a verified install", async () => {
		const { result } = renderHook(() => useJobsOfflineCache(false));

		await act(async () => result.current.enable());

		expect(result.current.status).toBe("ready");
		expect(mocks.resetWorker).toHaveBeenCalledTimes(1);
		expect(mocks.invalidateSnapshot).toHaveBeenCalledTimes(1);
		expect(mocks.resetWorker.mock.invocationCallOrder[0]).toBeGreaterThan(
			mocks.prepare.mock.invocationCallOrder[0],
		);
	});

	it("disposes stale readers before deleting an opted-out cache", async () => {
		const { result } = renderHook(() => useJobsOfflineCache(false));

		await act(async () => result.current.disable());

		expect(result.current.status).toBe("off");
		expect(mocks.resetWorker.mock.invocationCallOrder[0]).toBeLessThan(
			mocks.disable.mock.invocationCallOrder[0],
		);
		expect(mocks.invalidateSnapshot.mock.invocationCallOrder[0]).toBeLessThan(
			mocks.disable.mock.invocationCallOrder[0],
		);
	});

	it("disposes readers when integrity verification discards the ready cache", async () => {
		mocks.optedIn = true;
		mocks.ready = receipt;
		mocks.verify.mockImplementation(async () => {
			mocks.ready = null;
			throw new Error("cached bytes failed verification");
		});
		const { result } = renderHook(() => useJobsOfflineCache(true));

		await waitFor(() => expect(result.current.status).toBe("error"));

		expect(result.current.ready).toBeNull();
		expect(mocks.resetWorker).toHaveBeenCalledTimes(1);
		expect(mocks.invalidateSnapshot).toHaveBeenCalledTimes(1);
	});
});
