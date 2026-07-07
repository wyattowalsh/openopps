import { describe, expect, it } from "vitest";

import {
	DEFAULT_JOB_BOARD_FILTERS,
	type JobBoardFilters,
} from "@/components/jobs-board/jobs-board-filter-engine";

import {
	activeFilterChips,
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
