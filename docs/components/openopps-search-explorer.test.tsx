import { describe, expect, it } from "vitest";

import {
	DEFAULT_EXPLORER_FILTERS,
	DEFAULT_EXPLORER_SORT,
	activeFilterCount,
} from "@/components/openopps-search/explorer-filter-engine";
import { shouldLoadFullJobsIndexForExplorer } from "@/components/openopps-search/explorer-load-state";

describe("OpenOppsSearchExplorer", () => {
	it("clears stale full-index loading when filters are cleared before the request settles", () => {
		const filteredCount = activeFilterCount("jobs", {
			...DEFAULT_EXPLORER_FILTERS,
			query: "engineer",
		});
		expect(filteredCount).toBe(1);
		expect(
			shouldLoadFullJobsIndexForExplorer({
				entity: "jobs",
				hasJobsChunk: true,
				fullJobsLoaded: false,
				fullJobsRequested: false,
				fullJobsError: null,
				activeFilterCount: filteredCount,
				sortKey: DEFAULT_EXPLORER_SORT.jobs,
				defaultJobsSort: DEFAULT_EXPLORER_SORT.jobs,
			}),
		).toBe(true);

		const clearedCount = activeFilterCount("jobs", DEFAULT_EXPLORER_FILTERS);
		expect(clearedCount).toBe(0);
		expect(
			shouldLoadFullJobsIndexForExplorer({
				entity: "jobs",
				hasJobsChunk: true,
				fullJobsLoaded: false,
				fullJobsRequested: false,
				fullJobsError: null,
				activeFilterCount: clearedCount,
				sortKey: DEFAULT_EXPLORER_SORT.jobs,
				defaultJobsSort: DEFAULT_EXPLORER_SORT.jobs,
			}),
		).toBe(false);
	});
});
