import { describe, expect, it } from "vitest";

import {
	filterQueryOptions,
	JOB_FILTER_DEBOUNCE_MS,
	jobBoardQueryParsers,
	selectedJobQueryOptions,
} from "./jobs-board-filter-state";

describe("jobs board URL state policy", () => {
	it("replaces history for live filters and pushes history for selected jobs", () => {
		expect(filterQueryOptions).toMatchObject({
			history: "replace",
			shallow: true,
			clearOnDefault: true,
		});
		expect(selectedJobQueryOptions).toMatchObject({
			history: "push",
			shallow: true,
			clearOnDefault: true,
		});
	});

	it("debounces live search URL updates", () => {
		expect(JOB_FILTER_DEBOUNCE_MS).toBe(200);
		expect(filterQueryOptions.limitUrlUpdates).toEqual({
			method: "debounce",
			timeMs: JOB_FILTER_DEBOUNCE_MS,
		});
	});

	it("tracks the search result page in shareable URL state", () => {
		expect(Object.keys(jobBoardQueryParsers)).toContain("page");
	});
});
