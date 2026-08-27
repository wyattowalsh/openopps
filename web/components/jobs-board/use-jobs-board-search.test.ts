// @vitest-environment jsdom

import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_JOB_BOARD_FILTERS } from "@/components/jobs-board/jobs-board-filter-engine";
import { JOBS_BOARD_PAGE_SIZE } from "@/components/jobs-board/jobs-board-constants";
import type { SearchManifest } from "@/components/openopps-search/search-types";

import {
	resolveJobsBoardSortKey,
	useJobsBoardSearch,
} from "./use-jobs-board-search";

const mocks = vi.hoisted(() => ({
	loadJobsSearchResults: vi.fn(),
	trackTelemetry: vi.fn(),
}));

vi.mock("@/components/openopps-search/search-index-loader", () => ({
	loadJobsSearchResults: mocks.loadJobsSearchResults,
}));

vi.mock("@/lib/telemetry", () => ({
	trackTelemetry: mocks.trackTelemetry,
}));

const idleManifest = { version: 6 } as SearchManifest;

const pageOneResult = {
	rows: [["job-1"]],
	totalMatches: 12,
	truncated: false,
	limit: JOBS_BOARD_PAGE_SIZE,
	page: 1,
	pageSize: JOBS_BOARD_PAGE_SIZE,
	totalPages: 1,
	hasNextPage: false,
	hasPreviousPage: false,
};

beforeEach(() => {
	mocks.loadJobsSearchResults.mockReset();
	mocks.trackTelemetry.mockReset();
	mocks.loadJobsSearchResults.mockImplementation(
		async (
			_filters: unknown,
			_sortKey: unknown,
			options: { signal?: AbortSignal } = {},
		) => {
			if (options.signal?.aborted) {
				throw new DOMException("Aborted", "AbortError");
			}
			return pageOneResult;
		},
	);
});

afterEach(() => {
	cleanup();
});

describe("resolveJobsBoardSortKey", () => {
	it("uses latest for an empty query and relevance once a query is present", () => {
		expect(resolveJobsBoardSortKey("")).toBe("latest");
		expect(resolveJobsBoardSortKey("platform")).toBe("relevance");
	});
});

describe("useJobsBoardSearch", () => {
	it("loads page 1 of latest open jobs when no query or extra filters are set", async () => {
		const setPage = vi.fn();
		const { result } = renderHook(() =>
			useJobsBoardSearch({
				manifest: idleManifest,
				deferredFilters: DEFAULT_JOB_BOARD_FILTERS,
				page: 1,
				setPage,
				activeFilterCount: 0,
				sortKey: resolveJobsBoardSortKey(DEFAULT_JOB_BOARD_FILTERS.query),
			}),
		);

		await waitFor(() => {
			expect(result.current.searchRows).toEqual([["job-1"]]);
		});

		expect(mocks.loadJobsSearchResults).toHaveBeenCalledWith(
			DEFAULT_JOB_BOARD_FILTERS,
			"latest",
			expect.objectContaining({
				page: 1,
				pageSize: JOBS_BOARD_PAGE_SIZE,
			}),
		);
		expect(result.current.searchMeta).toMatchObject({
			totalMatches: 12,
			page: 1,
			pageSize: JOBS_BOARD_PAGE_SIZE,
			labeledAsMatches: false,
		});
		expect(result.current.searchLoading).toBe(false);
		expect(result.current.searchError).toBeNull();
		expect(setPage).not.toHaveBeenCalled();
	});

	it("labels query results as matches instead of idle open jobs", async () => {
		const filters = { ...DEFAULT_JOB_BOARD_FILTERS, query: "platform" };
		const { result } = renderHook(() =>
			useJobsBoardSearch({
				manifest: idleManifest,
				deferredFilters: filters,
				page: 1,
				setPage: vi.fn(),
				activeFilterCount: 1,
				sortKey: resolveJobsBoardSortKey(filters.query),
			}),
		);

		await waitFor(() => {
			expect(result.current.searchMeta?.labeledAsMatches).toBe(true);
		});
		expect(mocks.loadJobsSearchResults).toHaveBeenCalledWith(
			filters,
			"relevance",
			expect.objectContaining({
				page: 1,
				pageSize: JOBS_BOARD_PAGE_SIZE,
			}),
		);
	});

	it("does not fetch until a search manifest exists", async () => {
		renderHook(() =>
			useJobsBoardSearch({
				manifest: null,
				deferredFilters: DEFAULT_JOB_BOARD_FILTERS,
				page: 1,
				setPage: vi.fn(),
				activeFilterCount: 0,
				sortKey: "latest",
			}),
		);

		await Promise.resolve();
		expect(mocks.loadJobsSearchResults).not.toHaveBeenCalled();
	});
});
