import { describe, expect, it } from "vitest";

import type { SearchRow } from "@/components/openopps-search/search-types";

import { findJobRowById, resolveSelectedJobRow } from "./jobs-board-load-state";

describe("jobs board row selection state", () => {
	const rows = [jobRow("job-a"), jobRow("job-b")];

	it("finds loaded job rows by trimmed id", () => {
		expect(findJobRowById([jobRow(" job-a ")], "job-a")).toEqual(
			jobRow(" job-a "),
		);
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
