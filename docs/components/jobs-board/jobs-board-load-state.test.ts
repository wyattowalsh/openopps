import { describe, expect, it } from "vitest";

import type { SearchRow } from "@/components/openopps-search/search-types";

import {
	FULL_JOBS_INDEX_ROW_THRESHOLD,
	findJobRowById,
	needsFullJobsIndexConfirmation,
	resolveSelectedJobRow,
	shouldLoadFullJobsIndex,
} from "./jobs-board-load-state";

describe("jobs board full-index load state", () => {
	const rows = [jobRow("job-a"), jobRow("job-b")];

	it("does not load the full index before filters or selection", () => {
		expect(
			shouldLoadFullJobsIndex({
				activeFilterCount: 0,
				rows,
			}),
		).toBe(false);
	});

	it("does not load the full index when the selected job is already loaded", () => {
		expect(
			shouldLoadFullJobsIndex({
				activeFilterCount: 0,
				rows,
				selectedJobId: "job-a",
			}),
		).toBe(false);
	});

	it("loads the full index when the selected job is missing from loaded rows", () => {
		expect(
			shouldLoadFullJobsIndex({
				activeFilterCount: 0,
				rows,
				selectedJobId: "job-c",
			}),
		).toBe(true);
	});

	it("does not automatically reload when a missing selected job already triggered a full-index error", () => {
		expect(
			shouldLoadFullJobsIndex({
				activeFilterCount: 0,
				rows,
				selectedJobId: "job-c",
				fullIndexError: "Unable to load jobs.",
			}),
		).toBe(false);
	});

	it("loads the full index whenever filters are active", () => {
		expect(
			shouldLoadFullJobsIndex({
				activeFilterCount: 1,
				rows,
				selectedJobId: "job-a",
			}),
		).toBe(true);
	});

	it("does not automatically reload when active filters already triggered a full-index error", () => {
		expect(
			shouldLoadFullJobsIndex({
				activeFilterCount: 1,
				rows,
				selectedJobId: "job-a",
				fullIndexError: "Unable to load jobs.",
			}),
		).toBe(false);
	});

	it("permits retry after a full-index error is cleared", () => {
		expect(
			shouldLoadFullJobsIndex({
				activeFilterCount: 1,
				rows,
				selectedJobId: "job-a",
				fullIndexError: null,
			}),
		).toBe(true);
		expect(
			shouldLoadFullJobsIndex({
				activeFilterCount: 0,
				rows,
				selectedJobId: "job-c",
				fullIndexError: null,
			}),
		).toBe(true);
	});

	it("requires explicit confirmation before loading very large job snapshots", () => {
		const largeJobCount = FULL_JOBS_INDEX_ROW_THRESHOLD + 1;
		const decision = {
			activeFilterCount: 1,
			rows,
			selectedJobId: "job-a",
			jobCount: largeJobCount,
		};

		expect(needsFullJobsIndexConfirmation(decision)).toBe(true);
		expect(shouldLoadFullJobsIndex(decision)).toBe(false);
		expect(
			shouldLoadFullJobsIndex({
				...decision,
				fullIndexConfirmed: true,
			}),
		).toBe(true);
	});

	it("does not require confirmation for smaller snapshots", () => {
		expect(
			shouldLoadFullJobsIndex({
				activeFilterCount: 1,
				rows,
				jobCount: FULL_JOBS_INDEX_ROW_THRESHOLD,
			}),
		).toBe(true);
	});

	it("finds loaded job rows by trimmed id", () => {
		expect(findJobRowById([jobRow(" job-a ")], "job-a")).toEqual(jobRow(" job-a "));
	});

	it("resolves selected rows from visible rows first", () => {
		expect(
			resolveSelectedJobRow([jobRow("job-a")], [jobRow("job-b")], "job-a"),
		).toEqual(jobRow("job-a"));
	});

	it("falls back to loaded rows when filters hide the selected row", () => {
		expect(resolveSelectedJobRow([], rows, "job-b")).toEqual(jobRow("job-b"));
	});

	it("returns null for missing selected rows", () => {
		expect(resolveSelectedJobRow([], rows, "job-c")).toBeNull();
	});
});

function jobRow(id: string): SearchRow {
	return [id];
}
