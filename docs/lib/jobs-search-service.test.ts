import { afterEach, describe, expect, it, vi } from "vitest";

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

import { searchPublicJobsIndex } from "./jobs-search-service";

afterEach(() => {
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
		expect(result.truncated).toBe(true);
		expect(result.rows[0][J.id]).toBe("newer");
		expect(fetchMock).toHaveBeenCalledTimes(3);
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
