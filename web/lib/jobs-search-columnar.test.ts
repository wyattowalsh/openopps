import { describe, expect, it } from "vitest";

import { DEFAULT_JOB_BOARD_FILTERS } from "@/components/jobs-board/jobs-board-filter-engine";
import type { SearchRow } from "@/components/openopps-search/search-types";
import {
	EXPECTED_JOB_COLUMNAR_COLUMNS,
	EXPECTED_JOB_COLUMNS,
	J,
	SEARCH_VERSION,
} from "@/components/openopps-search/search-utils";
import {
	columnarChunkFromRows,
	searchRowsFromColumnarChunk,
	validateColumnarJobsChunk,
} from "@/lib/jobs-search-columnar";
import { JobsSearchEngine } from "@/lib/jobs-search-engine-core";

describe("columnar jobs snapshot", () => {
	const rows: SearchRow[] = [
		row({ id: "open-new", latestObserved: "2026-08-02T00:00:00Z" }),
		row({ id: "open-old", latestObserved: "2026-07-01T00:00:00Z" }),
		row({
			id: "closed-row",
			status: "closed",
			latestObserved: "2026-08-03T00:00:00Z",
		}),
	];

	it("keeps columns 0-14 and 17-21 including snippet and skillTokens", () => {
		expect(EXPECTED_JOB_COLUMNAR_COLUMNS).toEqual([
			"id",
			"sourceKey",
			"boardKey",
			"providerId",
			"status",
			"title",
			"company",
			"department",
			"team",
			"workplaceType",
			"remote",
			"employmentType",
			"locations",
			"salaryMin",
			"salaryMax",
			"postedAt",
			"latestObservedAt",
			"sourceKeys",
			"descriptionSnippet",
			"skillTokens",
		]);
		expect(EXPECTED_JOB_COLUMNAR_COLUMNS).not.toContain("descriptionHtml");
		expect(EXPECTED_JOB_COLUMNAR_COLUMNS).not.toContain("contentHash");
		const chunk = columnarChunkFromRows(rows);
		expect(chunk.version).toBe(SEARCH_VERSION);
		expect(chunk.version).not.toBe(7);
		expect(chunk.values[EXPECTED_JOB_COLUMNAR_COLUMNS.indexOf("status")]).toContain("closed");
		const inflated = searchRowsFromColumnarChunk(chunk);
		expect(inflated).toHaveLength(3);
		expect(inflated[0][J.descriptionSnippet]).toBe("Build reliable services with Python.");
		expect(inflated[0][J.skillTokens]).toBe("python kubernetes aws");
		expect(inflated[0][J.currency]).toBeNull();
		expect(inflated[0][J.firstSeenAt]).toBeNull();
		expect(inflated[2][J.status]).toBe("closed");
	});

	it("rejects payload version 7", () => {
		expect(() =>
			validateColumnarJobsChunk({
				...columnarChunkFromRows(rows),
				version: 7,
			}),
		).toThrow(/version 7/);
	});

	it("matches oracle page-2 on inflated list+filter rows", () => {
		const inflated = searchRowsFromColumnarChunk(columnarChunkFromRows(rows));
		const engine = new JobsSearchEngine({
			manifest: {
				version: SEARCH_VERSION,
				snapshotAt: "2026-08-26T21:52:25.592259Z",
				entities: {
					jobs: { columns: [...EXPECTED_JOB_COLUMNS], count: inflated.length },
					boards: { columns: [], count: 0 },
					providers: { columns: [], count: 0 },
				},
			} as never,
			rows: inflated,
		});
		const page2 = engine.search({
			filters: DEFAULT_JOB_BOARD_FILTERS,
			sortKey: "latest",
			page: 2,
			pageSize: 1,
		});
		expect(page2.page).toBe(2);
		expect(page2.rows).toHaveLength(1);
		expect(page2.rows[0][J.id]).toBe("open-old");
		expect(page2.complete).toBe(true);
		const allIndexed = engine.search({
			filters: { ...DEFAULT_JOB_BOARD_FILTERS, includeAllIndexed: true },
			sortKey: "latest",
			page: 1,
			pageSize: 10,
		});
		expect(allIndexed.rows.map((item) => item[J.id])).toContain("closed-row");
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
