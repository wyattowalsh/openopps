import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
	clearSearchIndexLoaderCacheForTests,
	loadEntityChunk,
	loadInitialJobsChunk,
	loadJobsSearchResults,
	loadSearchManifest,
} from "./search-index-loader";
import type { SearchChunk, SearchManifest } from "./search-types";
import {
	EXPECTED_BOARD_COLUMNS,
	EXPECTED_JOB_COLUMNS,
	EXPECTED_PROVIDER_COLUMNS,
	LEGACY_JOB_COLUMNS,
	SEARCH_VERSION,
} from "./search-utils";

const manifest: SearchManifest = {
	version: SEARCH_VERSION,
	snapshotAt: "2026-01-01T00:00:00Z",
	openJobCount: 2,
	counts: {
		snapshot: {
			database: "kaggle/openoppsdb.sqlite",
			sourceRows: 2,
			providerRoutes: 1,
			boards: 1,
			jobs: 2,
			openJobs: 2,
		},
	},
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
		locations: [],
		departments: [],
		teams: [],
		companies: [],
		skills: [],
		salaryCurrencies: [],
	},
	suggestions: {
		locations: [
			{
				value: "Remote",
				label: "Remote",
				count: 2,
				normalized: "remote",
			},
		],
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

	it("evicts failed fetches so the next request can retry", async () => {
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
			.mockResolvedValueOnce({
				ok: true,
				status: 200,
				json: async () => manifest,
			});
		vi.stubGlobal("fetch", fetchMock);

		await expect(loadSearchManifest()).rejects.toThrow(
			"Unable to load /data/openopps-search/manifest.json: 503",
		);
		await expect(loadSearchManifest()).resolves.toEqual(manifest);
		expect(fetchMock).toHaveBeenCalledTimes(2);
	});

	it("evicts invalid manifests so retry can refetch corrected JSON", async () => {
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce({
				ok: true,
				status: 200,
				json: async () => ({
					...manifest,
					entities: {
						...manifest.entities,
						boards: {
							...manifest.entities.boards,
							columns: ["bad"],
						},
					},
				}),
			})
			.mockResolvedValueOnce({
				ok: true,
				status: 200,
				json: async () => manifest,
			});
		vi.stubGlobal("fetch", fetchMock);

		await expect(loadSearchManifest()).rejects.toMatchObject({
			name: "SearchLoadError",
			code: "invalid_manifest",
		});
		await expect(loadSearchManifest()).resolves.toEqual(manifest);
		expect(fetchMock).toHaveBeenCalledTimes(2);
	});

	it("evicts invalid single-file chunks so retry can refetch corrected JSON", async () => {
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce({
				ok: true,
				status: 200,
				json: async () => ({ ...boards, columns: ["bad"] }),
			})
			.mockResolvedValueOnce({
				ok: true,
				status: 200,
				json: async () => boards,
			});
		vi.stubGlobal("fetch", fetchMock);

		await expect(loadEntityChunk(manifest, "boards")).rejects.toMatchObject({
			name: "SearchLoadError",
			code: "invalid_chunk",
		});
		await expect(loadEntityChunk(manifest, "boards")).resolves.toEqual(boards);
		expect(fetchMock).toHaveBeenCalledTimes(2);
	});

	it("evicts invalid chunk refs so retry can refetch corrected JSON", async () => {
		let secondChunkAttempts = 0;
		const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
			const path = String(input);
			if (path.endsWith("0000.json")) {
				return { ok: true, status: 200, json: async () => firstJobs };
			}
			secondChunkAttempts += 1;
			if (secondChunkAttempts === 1) {
				return {
					ok: true,
					status: 200,
					json: async () => ({ ...secondJobs, columns: ["bad"] }),
				};
			}
			return { ok: true, status: 200, json: async () => secondJobs };
		});
		vi.stubGlobal("fetch", fetchMock);

		await expect(loadEntityChunk(manifest, "jobs")).rejects.toMatchObject({
			name: "SearchLoadError",
			code: "invalid_chunk",
		});
		await expect(loadEntityChunk(manifest, "jobs")).resolves.toMatchObject({
			rows: [["first"], ["second"]],
		});
		expect(fetchMock).toHaveBeenCalledTimes(3);
	});

	it("rejects unsupported manifest versions with typed errors", async () => {
		stubFetch({
			"/data/openopps-search/manifest.json": {
				...manifest,
				version: 2,
			},
		});

		await expect(loadSearchManifest()).rejects.toMatchObject({
			name: "SearchLoadError",
			code: "unsupported_version",
		});
	});

	it("loads committed v3 artifacts while v4 generation requires a local database", async () => {
		const legacyManifest: SearchManifest = {
			...manifest,
			version: 3,
			counts: undefined,
			suggestions: undefined,
			dashboard: undefined,
			entities: {
				...manifest.entities,
				jobs: {
					...manifest.entities.jobs,
					columns: LEGACY_JOB_COLUMNS,
				},
			},
		};
		const legacyBoards = chunk("boards", EXPECTED_BOARD_COLUMNS, [["board"]], 3);
		const legacyJobs = chunk("jobs", LEGACY_JOB_COLUMNS, [["legacy"]], 3);
		stubFetch({
			"/data/openopps-search/manifest.json": legacyManifest,
			"/data/openopps-search/boards.json": legacyBoards,
			"/data/openopps-search/jobs/latest.json": legacyJobs,
		});

		await expect(loadSearchManifest()).resolves.toEqual(legacyManifest);
		await expect(loadEntityChunk(legacyManifest, "boards")).resolves.toEqual(
			legacyBoards,
		);
		await expect(loadInitialJobsChunk(legacyManifest)).resolves.toEqual(
			legacyJobs,
		);
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

	it("loads bounded jobs search results from the API route", async () => {
		const response = {
			...chunk("jobs", EXPECTED_JOB_COLUMNS, [["job-a"]]),
			totalMatches: 42,
			limit: 1,
			truncated: true,
		};
		const fetchMock = stubFetch({
			"/api/jobs/search?q=platform&wide=1&source=a16z&sort=relevance&limit=1":
				response,
		});

		await expect(
			loadJobsSearchResults(
				{
					query: "platform",
					wide: true,
					source: "a16z",
					provider: "",
					location: "",
					department: "",
					team: "",
					workplace: "",
					remote: "",
					employment: "",
					skill: "",
					salaryMin: "",
					salaryMax: "",
					postedAfter: "",
					postedBefore: "",
				},
				"relevance",
				{ limit: 1 },
			),
		).resolves.toEqual(response);
		expect(fetchMock).toHaveBeenCalledWith(
			"/api/jobs/search?q=platform&wide=1&source=a16z&sort=relevance&limit=1",
			{ cache: "force-cache", signal: undefined },
		);
	});
});

function chunk(
	entity: SearchChunk["entity"],
	columns: string[],
	rows: SearchChunk["rows"],
	version = SEARCH_VERSION,
): SearchChunk {
	return {
		version,
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
