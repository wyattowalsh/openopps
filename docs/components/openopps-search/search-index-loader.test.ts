import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
	clearSearchIndexLoaderCacheForTests,
	loadEntityChunk,
	loadInitialJobsChunk,
	loadSearchManifest,
} from "./search-index-loader";
import type { SearchChunk, SearchManifest } from "./search-types";
import {
	EXPECTED_BOARD_COLUMNS,
	EXPECTED_JOB_COLUMNS,
	EXPECTED_PROVIDER_COLUMNS,
	SEARCH_VERSION,
} from "./search-utils";

const manifest: SearchManifest = {
	version: SEARCH_VERSION,
	snapshotAt: "2026-01-01T00:00:00Z",
	openJobCount: 2,
	source: { database: "kaggle/openoppsdb.sqlite", tables: [] },
	defaultEntity: "jobs",
	defaultFilters: { jobs: { status: "open" } },
	detailShards: {
		root: "/data/openopps-search/jobs-details",
		format: "bucket-map",
		bucketCount: 256,
		count: 2,
	},
	entities: {
		jobs: {
			path: "/data/openopps-search/jobs/latest.json",
			file: "jobs/latest.json",
			initialPath: "/data/openopps-search/jobs/latest.json",
			chunkSize: 1,
			columns: EXPECTED_JOB_COLUMNS,
			count: 2,
			chunks: [
				{
					index: 1,
					path: "/data/openopps-search/jobs/chunks/0001.json",
					file: "jobs/chunks/0001.json",
					count: 1,
				},
				{
					index: 0,
					path: "/data/openopps-search/jobs/chunks/0000.json",
					file: "jobs/chunks/0000.json",
					count: 1,
				},
			],
		},
		boards: {
			path: "/data/openopps-search/boards.json",
			file: "boards.json",
			columns: EXPECTED_BOARD_COLUMNS,
			count: 1,
		},
		providers: {
			path: "/data/openopps-search/providers.json",
			file: "providers.json",
			columns: EXPECTED_PROVIDER_COLUMNS,
			count: 1,
		},
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

const latestJobs = chunk("jobs", EXPECTED_JOB_COLUMNS, [["latest"]]);
const firstJobs = chunk("jobs", EXPECTED_JOB_COLUMNS, [["first"]]);
const secondJobs = chunk("jobs", EXPECTED_JOB_COLUMNS, [["second"]]);
const boards = chunk("boards", EXPECTED_BOARD_COLUMNS, [["board"]]);

beforeEach(() => {
	clearSearchIndexLoaderCacheForTests();
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe("search index loader", () => {
	it("loads and validates the manifest", async () => {
		const fetchMock = stubFetch({
			"/data/openopps-search/manifest.json": manifest,
		});

		await expect(loadSearchManifest()).resolves.toEqual(manifest);
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	it("loads single-file entities", async () => {
		stubFetch({
			"/data/openopps-search/boards.json": boards,
		});

		await expect(loadEntityChunk(manifest, "boards")).resolves.toEqual(boards);
	});

	it("loads chunked entities in chunk-index order", async () => {
		stubFetch({
			"/data/openopps-search/jobs/chunks/0000.json": firstJobs,
			"/data/openopps-search/jobs/chunks/0001.json": secondJobs,
		});

		const loaded = await loadEntityChunk(manifest, "jobs");

		expect(loaded.rows).toEqual([["first"], ["second"]]);
		expect(loaded.count).toBe(2);
	});

	it("deduplicates repeated chunk fetches", async () => {
		const fetchMock = stubFetch({
			"/data/openopps-search/jobs/chunks/0000.json": firstJobs,
			"/data/openopps-search/jobs/chunks/0001.json": secondJobs,
		});

		await Promise.all([
			loadEntityChunk(manifest, "jobs"),
			loadEntityChunk(manifest, "jobs"),
		]);

		expect(fetchMock).toHaveBeenCalledTimes(2);
	});

	it("loads the bounded initial jobs chunk", async () => {
		const fetchMock = stubFetch({
			"/data/openopps-search/jobs/latest.json": latestJobs,
		});

		await expect(loadInitialJobsChunk(manifest)).resolves.toEqual(latestJobs);
		expect(fetchMock).toHaveBeenCalledWith(
			"/data/openopps-search/jobs/latest.json",
			{ cache: "force-cache" },
		);
	});
});

function chunk(
	entity: SearchChunk["entity"],
	columns: string[],
	rows: SearchChunk["rows"],
): SearchChunk {
	return {
		version: SEARCH_VERSION,
		entity,
		columns,
		count: rows.length,
		rows,
	};
}

function stubFetch(responses: Record<string, unknown>) {
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const path = String(input);
		const payload = responses[path];
		if (!payload) {
			return { ok: false, status: 404, json: async () => ({}) };
		}
		return { ok: true, status: 200, json: async () => payload };
	});
	vi.stubGlobal("fetch", fetchMock);
	return fetchMock;
}
