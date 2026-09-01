import { describe, expect, it } from "vitest";

import { DEFAULT_JOB_BOARD_FILTERS } from "@/components/jobs-board/jobs-board-filter-engine";
import { JOBS_BOARD_PAGE_SIZE } from "@/components/jobs-board/jobs-board-constants";
import {
	isDefaultJobsHomeView,
	t0PageRowsFromLatest,
	t0SidecarSearchMeta,
} from "@/components/jobs-board/jobs-board-t0";
import type { SearchRow } from "@/components/openopps-search/search-types";
import { J } from "@/components/openopps-search/search-utils";

function row(id: string, status: string, observed: string): SearchRow {
	const next: SearchRow = new Array(30).fill(null);
	next[J.id] = id;
	next[J.status] = status;
	next[J.latestObserved] = observed;
	next[J.title] = id;
	return next;
}

describe("jobs board T0 latest.json page-1", () => {
	it("gates the default open+latest page 1 view", () => {
		expect(isDefaultJobsHomeView(DEFAULT_JOB_BOARD_FILTERS, "latest", 1)).toBe(true);
		expect(isDefaultJobsHomeView(DEFAULT_JOB_BOARD_FILTERS, "latest", 2)).toBe(false);
		expect(isDefaultJobsHomeView(DEFAULT_JOB_BOARD_FILTERS, "relevance", 1)).toBe(false);
		expect(
			isDefaultJobsHomeView(
				{ ...DEFAULT_JOB_BOARD_FILTERS, query: "engineer" },
				"latest",
				1,
			),
		).toBe(false);
		expect(
			isDefaultJobsHomeView(
				{ ...DEFAULT_JOB_BOARD_FILTERS, includeAllIndexed: true },
				"latest",
				1,
			),
		).toBe(false);
	});

	it("paints 50 sorted open rows without advertising 250 as totalMatches", () => {
		const latest = Array.from({ length: 80 }, (_, index) =>
			row(
				`job-${String(index).padStart(3, "0")}`,
				index === 0 ? "closed" : "open",
				`2026-08-${String((index % 28) + 1).padStart(2, "0")}T00:00:00Z`,
			),
		);
		const pageRows = t0PageRowsFromLatest(latest);
		expect(pageRows).toHaveLength(JOBS_BOARD_PAGE_SIZE);
		expect(pageRows.some((item) => item[J.status] === "closed")).toBe(false);
		const meta = t0SidecarSearchMeta({ openJobCount: 11160, pageRows });
		expect(meta.totalMatches).toBe(11160);
		expect(meta.totalMatches).not.toBe(250);
		expect(meta.complete).toBe(false);
		expect(meta.hasNextPage).toBe(false);
		expect(meta.labeledAsMatches).toBe(false);
		expect(meta.truncated).toBe(true);
		expect(meta.pageSize).toBe(50);
		expect(meta.totalPages).toBe(Math.ceil(11160 / 50));
	});
});
