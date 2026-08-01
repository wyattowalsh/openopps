import { describe, expect, it, vi } from "vitest";

import {
	DEFAULT_JOB_BOARD_FILTERS,
	type JobBoardFilters,
} from "@/components/jobs-board/jobs-board-filter-engine";
import { baselineFromRows } from "@/components/jobs-board/jobs-board-local-state";
import { resolveCreateSavedSearchBaseline } from "@/components/jobs-board/jobs-board-save-search";
import type { JobsSearchSummaryResponse, SearchRow } from "@/components/openopps-search/search-types";
import { J } from "@/components/openopps-search/search-utils";

describe("resolveCreateSavedSearchBaseline", () => {
	const filters: JobBoardFilters = DEFAULT_JOB_BOARD_FILTERS;
	const sortKey = "latest" as const;
	const visibleRows = [jobRow("job-a"), jobRow("job-b")];

	it("uses cursor review status when summary load succeeds", async () => {
		const summary: JobsSearchSummaryResponse = {
			version: 6,
			entity: "jobs",
			snapshotAt: "2026-06-16T00:00:00.000Z",
			totalMatches: 42,
			sortKey: "latest",
			filtersHash: "{}",
		};
		const loadSummary = vi.fn().mockResolvedValue(summary);
		const now = "2026-06-30T12:00:00.000Z";

		const result = await resolveCreateSavedSearchBaseline({
			visibleRows,
			filters,
			sortKey,
			loadSummary,
			now,
		});

		expect(loadSummary).toHaveBeenCalledWith(filters, sortKey);
		expect(result).toEqual({
			baseline: baselineFromRows(visibleRows),
			baselineScope: "cursor",
			baselineTotalMatches: 42,
			reviewStatus: "current",
			reviewCursor: {
				semantics: "first-seen-v1",
				reviewedAt: now,
				snapshotAt: summary.snapshotAt,
			},
		});
	});

	it("falls back to page baseline when summary load fails", async () => {
		const loadSummary = vi.fn().mockRejectedValue(new Error("summary unavailable"));

		const result = await resolveCreateSavedSearchBaseline({
			visibleRows,
			filters,
			sortKey,
			loadSummary,
		});

		expect(loadSummary).toHaveBeenCalledWith(filters, sortKey);
		expect(result).toEqual({
			baseline: baselineFromRows(visibleRows),
			baselineScope: "page",
			baselineTotalMatches: visibleRows.length,
			reviewStatus: "needs-review",
			reviewCursor: null,
		});
	});

	it("uses page baseline for empty visible rows when summary fails", async () => {
		const loadSummary = vi.fn().mockRejectedValue(new Error("offline"));

		const result = await resolveCreateSavedSearchBaseline({
			visibleRows: [],
			filters,
			sortKey,
			loadSummary,
		});

		expect(result.baselineScope).toBe("page");
		expect(result.baselineTotalMatches).toBe(0);
		expect(result.baseline.reviewedJobIds).toEqual([]);
		expect(result.reviewStatus).toBe("needs-review");
		expect(result.reviewCursor).toBeNull();
	});
});

function jobRow(
	id: string,
	values: Partial<Record<keyof typeof J, string | number | null>> = {},
): SearchRow {
	const row: SearchRow = new Array(J.payloadHash + 1).fill(null);
	row[J.id] = id;
	row[J.source] = "a16z";
	row[J.board] = "acme";
	row[J.provider] = "greenhouse";
	row[J.status] = "open";
	row[J.title] = "Platform Engineer";
	row[J.company] = "Acme Corp";
	row[J.latestObserved] = "2026-06-16T10:00:00Z";
	row[J.descriptionSnippet] = "Build reliable platform services.";
	row[J.syncedAt] = "2026-06-16T10:00:00Z";
	for (const [key, value] of Object.entries(values)) {
		row[J[key as keyof typeof J]] = value;
	}
	return row;
}
