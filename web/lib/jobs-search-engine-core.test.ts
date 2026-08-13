import { describe, expect, it } from "vitest";

import {
	DEFAULT_JOB_BOARD_FILTERS,
	filterAndSortJobs,
	type JobBoardFilters,
	type JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import type {
	SearchManifest,
	SearchRow,
} from "@/components/openopps-search/search-types";
import {
	EXPECTED_BOARD_COLUMNS,
	EXPECTED_JOB_COLUMNS,
	EXPECTED_PROVIDER_COLUMNS,
	J,
	SEARCH_VERSION,
	text,
} from "@/components/openopps-search/search-utils";
import {
	JobsSearchEngine,
	MAX_FILTER_RESULT_CACHE_ROW_REFERENCES,
	createFrozenJobsSearchCorpus,
	frozenJobsSearchCases,
	normalizeJobsSearchFilters,
	normalizeJobsSearchSortKey,
	normalizePage,
	normalizePageSize,
} from "@/lib/jobs-search-engine-core";

describe("JobsSearchEngine", () => {
	const rows = [
		row({
			id: "platform-new",
			title: "Platform Engineer",
			sourceKeys: '["a16z","accel"]',
			firstSeenAt: "2026-07-04T00:00:00Z",
		}),
		row({
			id: "platform-old",
			title: "Platform Lead",
			company: "Cloud Works",
			latestObserved: "2026-06-01T00:00:00Z",
			firstSeenAt: "2026-05-01T00:00:00Z",
		}),
		row({
			id: "closed-platform",
			status: "closed",
			title: "Platform Architect",
			firstSeenAt: "2026-07-08T00:00:00Z",
		}),
		row({
			id: "sales",
			title: "Sales Manager",
			department: "Revenue",
			team: "Enterprise",
			provider: "lever",
			locations: '["New York, NY"]',
			workplace: "On-site",
			remote: "onsite",
			type: "Part-time",
			salaryMin: 70_000,
			salaryMax: 90_000,
			posted: "2026-05-01T00:00:00Z",
			skillTokens: "sales crm",
			firstSeenAt: "2026-05-01T00:00:00Z",
		}),
	];

	it("matches the frozen filter and ordering oracle across every semantic family", () => {
		const engine = new JobsSearchEngine({ manifest: manifest(rows.length), rows });
		const scenarios: Array<{ filters: Partial<JobBoardFilters>; sort: JobSortKey }> = [
			{ filters: { query: "platform" }, sort: "relevance" },
			{ filters: { query: "greenhouse", wide: true }, sort: "relevance" },
			{ filters: { includeAllIndexed: true, query: "platform" }, sort: "latest" },
			{ filters: { source: "a1", provider: "grnhse" }, sort: "latest" },
			{
				filters: {
					location: "sfo",
					department: "eng",
					team: "plat",
					workplace: "remote",
					remote: "REMOTE",
					employment: "ftime",
					skill: "kube",
				},
				sort: "latest",
			},
			{
				filters: {
					salaryMin: "150000",
					salaryMax: "200000",
					postedAfter: "2026-06-01",
					postedBefore: "2026-06-30",
				},
				sort: "latest",
			},
		];

		for (const scenario of scenarios) {
			const filters = { ...DEFAULT_JOB_BOARD_FILTERS, ...scenario.filters };
			const expected = filterAndSortJobs(rows, filters, scenario.sort).map((item) =>
				text(item[J.id]),
			);
			const actual = engine
				.search({ filters, sortKey: scenario.sort, pageSize: 100 })
				.rows.map((item) => text(item[J.id]));
			expect(actual, JSON.stringify(scenario)).toEqual(expected);
		}
	});

	it("keeps every result and page in the reproducible baseline corpus at oracle parity", () => {
		const frozenRows = createFrozenJobsSearchCorpus(2_400);
		const engine = new JobsSearchEngine({
			manifest: manifest(frozenRows.length),
			rows: frozenRows,
		});
		for (const scenario of frozenJobsSearchCases()) {
			const expectedAll = filterAndSortJobs(
				frozenRows,
				scenario.filters,
				scenario.sortKey,
			);
			const start = (scenario.page - 1) * scenario.pageSize;
			const result = engine.search(scenario);
			expect(result.rows, scenario.id).toEqual(
				expectedAll.slice(start, start + scenario.pageSize),
			);
			expect(result.totalMatches, scenario.id).toBe(expectedAll.length);
		}
	});

	it("clamps pagination and returns the complete stable metadata contract", () => {
		const engine = new JobsSearchEngine({ manifest: manifest(rows.length), rows });
		const result = engine.search({
			filters: DEFAULT_JOB_BOARD_FILTERS,
			sortKey: "latest",
			page: 99,
			pageSize: 2,
		});

		expect(result).toMatchObject({
			count: 1,
			totalMatches: 3,
			limit: 2,
			page: 2,
			pageSize: 2,
			totalPages: 2,
			hasNextPage: false,
			hasPreviousPage: true,
			truncated: true,
		});
		expect(result.rows[0][J.id]).toBe("platform-old");
	});

	it("preserves first-seen saved-count baselines for open and all-indexed searches", () => {
		const engine = new JobsSearchEngine({ manifest: manifest(rows.length), rows });
		const response = engine.countSavedSearches([
			{
				id: "open",
				filters: { ...DEFAULT_JOB_BOARD_FILTERS, query: "platform" },
				sortKey: "relevance",
				reviewedAt: "2026-07-01T00:00:00Z",
			},
			{
				id: "all",
				filters: {
					...DEFAULT_JOB_BOARD_FILTERS,
					query: "platform",
					includeAllIndexed: true,
				},
				sortKey: "relevance",
				reviewedAt: "2026-07-01T00:00:00Z",
			},
		]);

		expect(response).toEqual({
			version: SEARCH_VERSION,
			entity: "jobs",
			snapshotAt: "2026-07-10T00:00:00Z",
			semantics: "first-seen-v1",
			counts: [
				{ id: "open", totalMatches: 2, newMatches: 1 },
				{ id: "all", totalMatches: 3, newMatches: 2 },
			],
		});
	});

	it("aborts cooperative work before publishing a result", async () => {
		const largeRows = Array.from({ length: 10_000 }, (_, index) =>
			row({ id: `job-${index}`, title: `Platform Engineer ${index}` }),
		);
		const engine = new JobsSearchEngine({
			manifest: manifest(largeRows.length),
			rows: largeRows,
		});
		const controller = new AbortController();
		const result = engine.searchCooperative({
			filters: { ...DEFAULT_JOB_BOARD_FILTERS, query: "platform" },
			sortKey: "relevance",
			signal: controller.signal,
		});
		setTimeout(() => controller.abort(), 0);

		await expect(result).rejects.toMatchObject({ name: "AbortError" });
	});

	it("reports bounded typed-index storage separate from row payload bytes", () => {
		const stats = new JobsSearchEngine({ manifest: manifest(rows.length), rows }).stats();
		expect(stats).toMatchObject({ rows: rows.length });
		expect(stats.indexBytes).toBeGreaterThan(0);
		expect(stats.dictionaryValues).toBeGreaterThan(0);
	});

	it("caps cached broad-result references independently of the entry-count bound", () => {
		const broadRows = createFrozenJobsSearchCorpus(1_000).map((item) => {
			item[J.salaryMin] = 140_000;
			item[J.salaryMax] = 180_000;
			return item;
		});
		const engine = new JobsSearchEngine({
			manifest: manifest(broadRows.length),
			rows: broadRows,
			maxCachedRowReferences: 5_000,
		});
		for (let index = 1; index <= 8; index += 1) {
			engine.search({
				filters: {
					...DEFAULT_JOB_BOARD_FILTERS,
					includeAllIndexed: true,
					salaryMin: String(index),
				},
				sortKey: "latest",
				pageSize: 50,
			});
		}

		const stats = engine.stats();
		expect(MAX_FILTER_RESULT_CACHE_ROW_REFERENCES).toBe(250_000);
		expect(stats.maxCachedRowReferences).toBe(5_000);
		expect(stats.cachedResults).toBe(5);
		expect(stats.cachedRowReferences).toBe(5_000);
	});
});

describe("jobs search input normalization", () => {
	it("keeps historical defaults and bounds", () => {
		expect(normalizeJobsSearchFilters({ query: "platform" })).toEqual({
			...DEFAULT_JOB_BOARD_FILTERS,
			query: "platform",
		});
		expect(
			normalizeJobsSearchSortKey("unknown", {
				...DEFAULT_JOB_BOARD_FILTERS,
				query: "platform",
			}),
		).toBe("relevance");
		expect(normalizePage(-10)).toBe(1);
		expect(normalizePageSize(10_000)).toBe(100);
	});
});

function row(
	values: Partial<Record<keyof typeof J, string | number | null>>,
): SearchRow {
	const result: SearchRow = new Array(EXPECTED_JOB_COLUMNS.length).fill(null);
	result[J.id] = "job";
	result[J.source] = "a16z";
	result[J.board] = "acme";
	result[J.provider] = "greenhouse";
	result[J.status] = "open";
	result[J.title] = "Platform Engineer";
	result[J.company] = "Acme Corp";
	result[J.department] = "Engineering";
	result[J.team] = "Platform";
	result[J.workplace] = "Remote";
	result[J.remote] = "remote";
	result[J.type] = "Full-time";
	result[J.locations] = '["San Francisco, CA","Remote"]';
	result[J.salaryMin] = 140_000;
	result[J.salaryMax] = 180_000;
	result[J.currency] = "USD";
	result[J.url] = "https://example.test/jobs/1";
	result[J.posted] = "2026-06-01T00:00:00Z";
	result[J.latestObserved] = "2026-07-01T00:00:00Z";
	result[J.sourceKeys] = '["a16z"]';
	result[J.descriptionSnippet] = "Build reliable services with Python.";
	result[J.skillTokens] = "python kubernetes aws";
	result[J.syncedAt] = "2026-07-01T00:00:00Z";
	result[J.firstSeenAt] = "2026-06-01T00:00:00Z";
	for (const [key, value] of Object.entries(values)) {
		result[J[key as keyof typeof J]] = value;
	}
	return result;
}

function manifest(count: number): SearchManifest {
	return {
		version: SEARCH_VERSION,
		snapshotAt: "2026-07-10T00:00:00Z",
		source: { database: "fixture", tables: ["jobs"] },
		defaultEntity: "jobs",
		defaultFilters: { jobs: { status: "open" } },
		entities: {
			jobs: { count, columns: [...EXPECTED_JOB_COLUMNS], path: "/jobs.json" },
			boards: { count: 0, columns: [...EXPECTED_BOARD_COLUMNS], path: "/boards.json" },
			providers: {
				count: 0,
				columns: [...EXPECTED_PROVIDER_COLUMNS],
				path: "/providers.json",
			},
		},
		facets: {
			sources: [],
			providerIds: [],
			jobStatuses: ["open", "closed"],
			supportLevels: [],
			routeStatuses: [],
			workplaces: [],
			employmentTypes: [],
		},
	};
}
