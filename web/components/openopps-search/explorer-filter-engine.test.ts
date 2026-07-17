import { describe, expect, it } from "vitest";

import type { SearchRow } from "./search-types";
import { J } from "./search-utils";
import {
	activeFilterCount,
	DEFAULT_EXPLORER_FILTERS,
	type ExplorerFilters,
	matchesRow,
	sourceMatches,
} from "./explorer-filter-engine";

function makeJobRow(values: Partial<Record<keyof typeof J, string | number | null>>) {
	const row: SearchRow = new Array(23).fill(null);
	row[J.id] = "job-1";
	row[J.source] = "extantia";
	row[J.board] = "board-1";
	row[J.provider] = "greenhouse";
	row[J.status] = "open";
	row[J.title] = "Data Engineer";
	row[J.company] = "Acme";
	row[J.department] = "Engineering";
	row[J.team] = "Data";
	row[J.workplace] = "Remote";
	row[J.remote] = "remote";
	row[J.type] = "Full-time";
	row[J.locations] = '["New York, NY","Remote"]';
	row[J.url] = "https://example.com/job";
	row[J.latestObserved] = "2026-06-01T00:00:00Z";
	row[J.sourceKeys] = '["extantia","lightrock"]';
	for (const [key, value] of Object.entries(values)) {
		row[J[key as keyof typeof J]] = value;
	}
	return row;
}

describe("explorer-filter-engine", () => {
	it("matches jobs by secondary source keys", () => {
		const row = makeJobRow({});

		expect(sourceMatches("jobs", row, "lightrock")).toBe(true);
		expect(
			matchesRow(
				"jobs",
				row,
				{ ...DEFAULT_EXPLORER_FILTERS, source: "lightrock" },
				[],
				[],
			),
		).toBe(true);
	});

	it("falls back to primary source when sourceKeys are absent", () => {
		const row = makeJobRow({ source: "yc", sourceKeys: null });

		expect(sourceMatches("jobs", row, "yc")).toBe(true);
		expect(sourceMatches("jobs", row, "lightrock")).toBe(false);
	});

	it("keeps board and provider source matching exact", () => {
		const board: SearchRow = ["board-1", "yc"];
		const provider: SearchRow = ["provider-1", "a16z"];

		expect(sourceMatches("boards", board, "yc")).toBe(true);
		expect(sourceMatches("boards", board, "a16z")).toBe(false);
		expect(sourceMatches("providers", provider, "a16z")).toBe(true);
		expect(sourceMatches("providers", provider, "yc")).toBe(false);
	});

	it("honors default open-job status while filtering secondary sources", () => {
		const filters: ExplorerFilters = {
			...DEFAULT_EXPLORER_FILTERS,
			source: "lightrock",
		};

		expect(matchesRow("jobs", makeJobRow({ status: "open" }), filters, [], [])).toBe(true);
		expect(matchesRow("jobs", makeJobRow({ status: "closed" }), filters, [], [])).toBe(false);
	});

	it("does not count the default open job status as an active filter", () => {
		expect(activeFilterCount("jobs", DEFAULT_EXPLORER_FILTERS)).toBe(0);
	});

	it("counts Any job status as an active filter", () => {
		expect(
			activeFilterCount("jobs", {
				...DEFAULT_EXPLORER_FILTERS,
				jobStatus: "",
			}),
		).toBe(1);
	});

	it("counts non-default job statuses as active filters", () => {
		expect(
			activeFilterCount("jobs", {
				...DEFAULT_EXPLORER_FILTERS,
				jobStatus: "closed",
			}),
		).toBe(1);
	});

	it("matches every job status when the job status filter is Any", () => {
		const filters: ExplorerFilters = {
			...DEFAULT_EXPLORER_FILTERS,
			jobStatus: "",
		};

		expect(matchesRow("jobs", makeJobRow({ status: "open" }), filters, [], [])).toBe(true);
		expect(matchesRow("jobs", makeJobRow({ status: "closed" }), filters, [], [])).toBe(true);
	});
});
