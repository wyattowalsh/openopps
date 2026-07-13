import { afterEach, describe, expect, it, vi } from "vitest";

import * as jobsBoardFilterEngine from "@/components/jobs-board/jobs-board-filter-engine";
import {
	DEFAULT_JOB_BOARD_FILTERS,
	type JobBoardFilters,
} from "@/components/jobs-board/jobs-board-filter-engine";
import type { SearchChunk, SearchManifest, SearchRow } from "@/components/openopps-search/search-types";
import {
	EXPECTED_BOARD_COLUMNS,
	EXPECTED_JOB_COLUMNS,
	EXPECTED_PROVIDER_COLUMNS,
	J,
	SEARCH_VERSION,
} from "@/components/openopps-search/search-utils";

import {
	clearJobsSearchStoreForTests,
	jobsSearchStoreStatsForTests,
	searchPublicJobsIndex,
	summarizePublicJobsIndex,
} from "./jobs-search-service";

afterEach(() => {
	clearJobsSearchStoreForTests();
	vi.unstubAllGlobals();
});

describe("jobs search service", () => {
	it("searches public jobs chunks server-side and returns bounded results", async () => {
		const matchingNewer = row({ id: "newer", title: "Platform Engineer" });
		const matchingOlder = row({
			id: "older",
			title: "Platform Lead",
			latestObserved: "2026-06-01T00:00:00Z",
		});
		const ignored = row({ id: "ignored", title: "Sales Manager" });
		const fetchMock = stubFetch({
			"https://openopps.test/data/openopps-search/manifest.json": manifest,
			"https://openopps.test/data/openopps-search/jobs/chunks/0000.json": chunk([
				matchingOlder,
			]),
			"https://openopps.test/data/openopps-search/jobs/chunks/0001.json": chunk([
				ignored,
				matchingNewer,
			]),
		});

		const result = await searchPublicJobsIndex({
			baseUrl: "https://openopps.test/",
			filters: filters({ query: "platform" }),
			sortKey: "relevance",
			limit: 1,
		});

		expect(result.totalMatches).toBe(2);
		expect(result.count).toBe(1);
		expect(result.page).toBe(1);
		expect(result.pageSize).toBe(1);
		expect(result.totalPages).toBe(2);
		expect(result.hasNextPage).toBe(true);
		expect(result.hasPreviousPage).toBe(false);
			expect(result.truncated).toBe(true);
			expect(result.rows[0][J.id]).toBe("newer");
			expect(fetchMock).toHaveBeenCalledTimes(3);
		});

	it("fetches public artifacts for production hosts", async () => {
		const matching = row({ id: "prod", title: "Platform Engineer" });
		const fetchMock = stubFetch({
			"https://openopps.example/data/openopps-search/manifest.json": manifest,
			"https://openopps.example/data/openopps-search/jobs/chunks/0000.json": chunk([
				matching,
			]),
			"https://openopps.example/data/openopps-search/jobs/chunks/0001.json": chunk([]),
		});

		const result = await searchPublicJobsIndex({
			baseUrl: "https://openopps.example/api/jobs/search?q=platform",
			filters: filters({ query: "platform" }),
			sortKey: "relevance",
			page: 1,
			pageSize: 50,
		});

		expect(result.rows[0][J.id]).toBe("prod");
		expect(fetchMock).toHaveBeenCalledWith(
			new URL("https://openopps.example/data/openopps-search/manifest.json"),
			{ cache: "no-store" },
		);
	});

	it("reports failed public artifact fetches as search load errors", async () => {
		stubFetch({});

		await expect(
			searchPublicJobsIndex({
				baseUrl: "https://openopps.example/",
				filters: filters({ query: "platform" }),
				sortKey: "relevance",
			}),
		).rejects.toMatchObject({
			name: "SearchLoadError",
			code: "fetch_failed",
			path: "/data/openopps-search/manifest.json",
			message: expect.stringMatching(
				/Unable to load \/data\/openopps-search\/manifest\.json:.*404/,
			),
		});
	});

			it("reuses parsed chunks for later requests on the same server instance", async () => {
				const matchingNewer = row({ id: "newer", title: "Platform Engineer" });
				const matchingOlder = row({
				id: "older",
				title: "Platform Lead",
				latestObserved: "2026-06-01T00:00:00Z",
			});
			const fetchMock = stubFetch({
				"https://openopps.test/data/openopps-search/manifest.json": manifest,
				"https://openopps.test/data/openopps-search/jobs/chunks/0000.json": chunk([
					matchingOlder,
				]),
				"https://openopps.test/data/openopps-search/jobs/chunks/0001.json": chunk([
					matchingNewer,
				]),
			});

			await searchPublicJobsIndex({
				baseUrl: "https://openopps.test/",
				filters: filters({ query: "platform" }),
				sortKey: "relevance",
				page: 1,
				pageSize: 1,
			});
			const second = await searchPublicJobsIndex({
				baseUrl: "https://openopps.test/",
				filters: filters({ query: "platform" }),
				sortKey: "relevance",
				page: 2,
				pageSize: 1,
			});

			expect(second.rows[0][J.id]).toBe("older");
			expect(fetchMock).toHaveBeenCalledTimes(3);
			expect(jobsSearchStoreStatsForTests()).toEqual({
				loads: 1,
				chunkFetches: 2,
			});
		});

	it("returns later pages without loading a browser-side snapshot", async () => {
		const matchingNewer = row({ id: "newer", title: "Platform Engineer" });
		const matchingOlder = row({
			id: "older",
			title: "Platform Lead",
			latestObserved: "2026-06-01T00:00:00Z",
		});
		stubFetch({
			"https://openopps.test/data/openopps-search/manifest.json": manifest,
			"https://openopps.test/data/openopps-search/jobs/chunks/0000.json": chunk([
				matchingOlder,
			]),
			"https://openopps.test/data/openopps-search/jobs/chunks/0001.json": chunk([
				matchingNewer,
			]),
		});

		const result = await searchPublicJobsIndex({
			baseUrl: "https://openopps.test/",
			filters: filters({ query: "platform" }),
			sortKey: "relevance",
			page: 2,
			pageSize: 1,
		});

		expect(result.totalMatches).toBe(2);
		expect(result.count).toBe(1);
		expect(result.page).toBe(2);
		expect(result.pageSize).toBe(1);
		expect(result.totalPages).toBe(2);
		expect(result.hasNextPage).toBe(false);
		expect(result.hasPreviousPage).toBe(true);
		expect(result.rows[0][J.id]).toBe("older");
	});

	it("returns every row for the requested page when matches are larger than one page", async () => {
		const firstChunkRows = Array.from({ length: 70 }, (_, index) =>
			row({
				id: `first-${index}`,
				title: `Platform Engineer ${index}`,
				latestObserved: `2026-06-${String((index % 28) + 1).padStart(2, "0")}T00:00:00Z`,
			}),
		);
		const secondChunkRows = Array.from({ length: 50 }, (_, index) =>
			row({
				id: `second-${index}`,
				title: `Platform Engineer ${index + 70}`,
				latestObserved: `2026-05-${String((index % 28) + 1).padStart(2, "0")}T00:00:00Z`,
			}),
		);
		stubFetch({
			"https://openopps.test/data/openopps-search/manifest.json": {
				...manifest,
				openJobCount: 120,
				entities: {
					...manifest.entities,
					jobs: {
						...manifest.entities.jobs,
						count: 120,
						chunks: [
							{
								index: 0,
								path: "/data/openopps-search/jobs/chunks/0000.json",
								file: "jobs/chunks/0000.json",
								count: 70,
							},
							{
								index: 1,
								path: "/data/openopps-search/jobs/chunks/0001.json",
								file: "jobs/chunks/0001.json",
								count: 50,
							},
						],
					},
				},
			},
			"https://openopps.test/data/openopps-search/jobs/chunks/0000.json":
				chunk(firstChunkRows),
			"https://openopps.test/data/openopps-search/jobs/chunks/0001.json":
				chunk(secondChunkRows),
		});

		const result = await searchPublicJobsIndex({
			baseUrl: "https://openopps.test/",
			filters: filters({ query: "platform" }),
			sortKey: "relevance",
			page: 2,
			pageSize: 50,
		});

		expect(result.totalMatches).toBe(120);
		expect(result.count).toBe(50);
		expect(result.rows).toHaveLength(50);
		expect(result.page).toBe(2);
		expect(result.pageSize).toBe(50);
		expect(result.totalPages).toBe(3);
			expect(result.hasNextPage).toBe(true);
			expect(result.hasPreviousPage).toBe(true);
		});

		it("reuses filtered sorted rows for repeated requests with the same filters", async () => {
			const matchingNewer = row({ id: "newer", title: "Platform Engineer" });
			const matchingOlder = row({
				id: "older",
				title: "Platform Lead",
				latestObserved: "2026-06-01T00:00:00Z",
			});
			stubFetch({
				"https://openopps.test/data/openopps-search/manifest.json": manifest,
				"https://openopps.test/data/openopps-search/jobs/chunks/0000.json": chunk([
					matchingOlder,
				]),
				"https://openopps.test/data/openopps-search/jobs/chunks/0001.json": chunk([
					matchingNewer,
				]),
			});
			const filterSpy = vi.spyOn(jobsBoardFilterEngine, "filterAndSortJobs");

			const first = await searchPublicJobsIndex({
				baseUrl: "https://openopps.test/",
				filters: filters({ query: "platform" }),
				sortKey: "relevance",
				page: 1,
				pageSize: 1,
			});
			const second = await searchPublicJobsIndex({
				baseUrl: "https://openopps.test/",
				filters: filters({ query: "platform" }),
				sortKey: "relevance",
				page: 2,
				pageSize: 1,
			});

			expect(filterSpy).toHaveBeenCalledTimes(1);
			expect(first.rows[0][J.id]).toBe("newer");
			expect(second.rows[0][J.id]).toBe("older");
			expect(jobsSearchStoreStatsForTests()).toEqual({
				loads: 1,
				chunkFetches: 2,
			});
			filterSpy.mockRestore();
		});

		it("returns counts-only summary by default without fingerprint entries", async () => {
			const matchingNewer = row({
				id: "newer",
				title: "Platform Engineer",
				contentHash: "content-newer",
			});
			const matchingOlder = row({
				id: "older",
				title: "Platform Lead",
				contentHash: "content-older",
			});
			stubFetch({
				"https://openopps.test/data/openopps-search/manifest.json": manifest,
				"https://openopps.test/data/openopps-search/jobs/chunks/0000.json": chunk([
					matchingOlder,
				]),
				"https://openopps.test/data/openopps-search/jobs/chunks/0001.json": chunk([
					matchingNewer,
				]),
			});

			const result = await summarizePublicJobsIndex({
				baseUrl: "https://openopps.test/",
				filters: filters({ query: "platform" }),
				sortKey: "relevance",
			});

			expect(result.totalMatches).toBe(2);
			expect(result.entries).toEqual([]);
			expect(result.filtersHash).toContain('"query":"platform"');
		});

		it("returns fingerprint entries when includeFingerprints is enabled", async () => {
			const matchingNewer = row({
				id: "newer",
				title: "Platform Engineer",
				contentHash: "content-newer",
			});
			const matchingOlder = row({
				id: "older",
				title: "Platform Lead",
				latestObserved: "2026-06-01T00:00:00Z",
				contentHash: "content-older",
			});
			stubFetch({
				"https://openopps.test/data/openopps-search/manifest.json": manifest,
				"https://openopps.test/data/openopps-search/jobs/chunks/0000.json": chunk([
					matchingOlder,
				]),
				"https://openopps.test/data/openopps-search/jobs/chunks/0001.json": chunk([
					matchingNewer,
				]),
			});

			const result = await summarizePublicJobsIndex({
				baseUrl: "https://openopps.test/",
				filters: filters({ query: "platform" }),
				sortKey: "relevance",
				includeFingerprints: true,
			});

			expect(result.totalMatches).toBe(2);
			expect(result.entries).toEqual([
				{ id: "newer", fingerprint: "content-newer" },
				{ id: "older", fingerprint: "content-older" },
			]);
			expect(result.filtersHash).toContain('"query":"platform"');
		});
	});

const manifest: SearchManifest = {
	version: SEARCH_VERSION,
	snapshotAt: "2026-01-01T00:00:00Z",
	openJobCount: 3,
	source: { database: "kaggle/openoppsdb.sqlite", tables: [] },
	defaultEntity: "jobs",
	defaultFilters: { jobs: { status: "open" } },
	entities: {
		jobs: {
			path: "/data/openopps-search/jobs/latest.json",
			initialPath: "/data/openopps-search/jobs/latest.json",
			chunkSize: 2,
			columns: EXPECTED_JOB_COLUMNS,
			count: 3,
			chunks: [
				{
					index: 0,
					path: "/data/openopps-search/jobs/chunks/0000.json",
					file: "jobs/chunks/0000.json",
					count: 1,
				},
				{
					index: 1,
					path: "/data/openopps-search/jobs/chunks/0001.json",
					file: "jobs/chunks/0001.json",
					count: 2,
				},
			],
		},
		boards: {
			path: "/data/openopps-search/boards.json",
			columns: EXPECTED_BOARD_COLUMNS,
			count: 0,
		},
		providers: {
			path: "/data/openopps-search/providers.json",
			columns: EXPECTED_PROVIDER_COLUMNS,
			count: 0,
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
};

function chunk(rows: SearchRow[]): SearchChunk {
	return {
		version: SEARCH_VERSION,
		entity: "jobs",
		columns: EXPECTED_JOB_COLUMNS,
		count: rows.length,
		rows,
	};
}

function filters(overrides: Partial<JobBoardFilters>): JobBoardFilters {
	return { ...DEFAULT_JOB_BOARD_FILTERS, ...overrides };
}

function row(values: Partial<Record<keyof typeof J, string | number | null>>): SearchRow {
	const item: SearchRow = new Array(EXPECTED_JOB_COLUMNS.length).fill(null);
	item[J.id] = values.id ?? "job";
	item[J.status] = values.status ?? "open";
	item[J.title] = values.title ?? "Platform Engineer";
	item[J.company] = values.company ?? "Acme";
	item[J.latestObserved] = values.latestObserved ?? "2026-06-20T00:00:00Z";
	item[J.descriptionSnippet] = values.descriptionSnippet ?? "Build systems.";
	item[J.contentHash] = values.contentHash ?? null;
	item[J.payloadHash] = values.payloadHash ?? null;
	return item;
}

function stubFetch(responses: Record<string, unknown>) {
	const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		const payload = responses[url];
		if (!payload) {
			return { ok: false, status: 404, json: async () => ({}) };
		}
		return { ok: true, status: 200, json: async () => payload };
	});
	vi.stubGlobal("fetch", fetchMock);
	return fetchMock;
}
