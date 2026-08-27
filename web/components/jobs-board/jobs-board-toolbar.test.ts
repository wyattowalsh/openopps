import { describe, expect, it } from "vitest";

import {
	DEFAULT_JOB_BOARD_FILTERS,
	type JobBoardFilters,
} from "@/components/jobs-board/jobs-board-filter-engine";

import {
	activeFilterChips,
	jobsBoardToolbarCountLabel,
	removeFilterPatch,
} from "./jobs-board-toolbar";

describe("jobs board toolbar filters", () => {
	it("creates removable chips for active boolean and string filters", () => {
		const filters: JobBoardFilters = {
			...DEFAULT_JOB_BOARD_FILTERS,
			includeAllIndexed: true,
			source: "yc",
		};

		expect(activeFilterChips(filters)).toEqual([
			{ key: "includeAllIndexed", label: "All indexed", value: "enabled" },
			{ key: "source", label: "Source", value: "yc" },
		]);
	});

	it("clears boolean filter chips with boolean false patches", () => {
		expect(removeFilterPatch("wide")).toEqual({ wide: false });
		expect(removeFilterPatch("includeAllIndexed")).toEqual({
			includeAllIndexed: false,
		});
	});

	it("clears string filter chips with empty-string patches", () => {
		expect(removeFilterPatch("source")).toEqual({ source: "" });
	});
});

describe("jobsBoardToolbarCountLabel", () => {
	it("does not label unfiltered open jobs as matches while searching", () => {
		expect(
			jobsBoardToolbarCountLabel({
				matchCount: null,
				searchActive: true,
				includeAllIndexed: false,
			}),
		).toBe("Searching...");
	});

	it("shows match totals after search meta arrives", () => {
		expect(
			jobsBoardToolbarCountLabel({
				matchCount: 40,
				searchActive: true,
				includeAllIndexed: false,
			}),
		).toBe("40 matches");
	});

	it("keeps open-job copy when search is idle", () => {
		expect(
			jobsBoardToolbarCountLabel({
				matchCount: 88800,
				searchActive: false,
				includeAllIndexed: false,
			}),
		).toBe("88,800 open jobs");
		expect(
			jobsBoardToolbarCountLabel({
				matchCount: 90000,
				searchActive: false,
				includeAllIndexed: true,
			}),
		).toBe("90,000 indexed jobs");
	});
});
