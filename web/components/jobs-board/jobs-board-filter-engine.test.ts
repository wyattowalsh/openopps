import { describe, expect, it, vi } from "vitest";

import {
	DEFAULT_JOB_BOARD_FILTERS,
	filterAndSortJobs,
	jobMatchesFilters,
	type JobBoardFilters,
	postedAtInRange,
	queryMatches,
	relevanceScore,
	salaryOverlaps,
	skillMatches,
	sourceKeyMatches,
} from "@/components/jobs-board/jobs-board-filter-engine";
import * as searchJobCore from "@/lib/search-job-core";
import type { SearchRow } from "@/components/openopps-search/search-types";
import { formatSalary, J } from "@/components/openopps-search/search-utils";

function makeRow(values: Partial<Record<keyof typeof J, string | number | null>>) {
	const row: SearchRow = new Array(23).fill(null);
	row[J.id] = "job-1";
	row[J.source] = "a16z";
	row[J.board] = "acme";
	row[J.provider] = "greenhouse";
	row[J.status] = "open";
	row[J.title] = "Platform Engineer";
	row[J.company] = "Acme Corp";
	row[J.department] = "Engineering";
	row[J.team] = "Platform";
	row[J.workplace] = "Remote";
	row[J.remote] = "remote";
	row[J.type] = "Full-time";
	row[J.locations] = '["San Francisco, CA","Remote"]';
	row[J.salaryMin] = 140000;
	row[J.salaryMax] = 180000;
	row[J.currency] = "USD";
	row[J.url] = "https://example.com/jobs/1";
	row[J.posted] = "2026-06-01T10:00:00Z";
	row[J.latestObserved] = "2026-06-16T10:00:00Z";
	row[J.sourceKeys] = '["a16z","accel"]';
	row[J.descriptionSnippet] = "Build reliable platform services with Python.";
	row[J.skillTokens] = "python kubernetes aws";
	row[J.syncedAt] = "2026-06-16T10:00:00Z";

	for (const [key, value] of Object.entries(values)) {
		row[J[key as keyof typeof J]] = value;
	}
	return row;
}

describe("jobs-board-filter-engine", () => {
	const openRow = makeRow({});
	const closedRow = makeRow({ status: "closed" });

	it("filters open jobs only", () => {
		expect(jobMatchesFilters(openRow, DEFAULT_JOB_BOARD_FILTERS)).toBe(true);
		expect(jobMatchesFilters(closedRow, DEFAULT_JOB_BOARD_FILTERS)).toBe(false);
	});

	it("matches source keys from merged board keys", () => {
		expect(sourceKeyMatches(openRow, "accel")).toBe(true);
		expect(sourceKeyMatches(openRow, "sequoia")).toBe(false);
		expect(sourceKeyMatches(makeRow({ sourceKeys: null }), "a16z")).toBe(true);
	});

	it("supports fuzzy source key filters", () => {
		expect(sourceKeyMatches(openRow, "a1")).toBe(true);
		expect(sourceKeyMatches(makeRow({ sourceKeys: null, source: "climate-tech" }), "clmtech")).toBe(
			true,
		);
	});

	it("falls back to source key when sourceKeys is empty", () => {
		expect(sourceKeyMatches(makeRow({ sourceKeys: "[]", source: "yc" }), "yc")).toBe(true);
		expect(sourceKeyMatches(makeRow({ sourceKeys: "[]", source: "yc" }), "a16z")).toBe(false);
	});

	it("matches location, department, team, and employment substrings", () => {
		const filters: JobBoardFilters = {
			...DEFAULT_JOB_BOARD_FILTERS,
			location: "san francisco",
			department: "engineer",
			team: "platform",
			employment: "full",
		};
		expect(jobMatchesFilters(openRow, filters)).toBe(true);
	});

	it("rejects department mismatches", () => {
		expect(
			jobMatchesFilters(openRow, {
				...DEFAULT_JOB_BOARD_FILTERS,
				department: "sales",
			}),
		).toBe(false);
	});

	it("matches remote equality case-insensitively", () => {
		expect(
			jobMatchesFilters(openRow, {
				...DEFAULT_JOB_BOARD_FILTERS,
				remote: "REMOTE",
			}),
		).toBe(true);
		expect(
			jobMatchesFilters(openRow, {
				...DEFAULT_JOB_BOARD_FILTERS,
				remote: "hybrid",
			}),
		).toBe(false);
	});

	it("matches workplace or remote substrings", () => {
		expect(
			jobMatchesFilters(openRow, {
				...DEFAULT_JOB_BOARD_FILTERS,
				workplace: "remote",
			}),
		).toBe(true);
		expect(
			jobMatchesFilters(makeRow({ workplace: "On-site", remote: "hybrid" }), {
				...DEFAULT_JOB_BOARD_FILTERS,
				workplace: "hybrid",
			}),
		).toBe(true);
	});

	it("matches provider exactly", () => {
		expect(
			jobMatchesFilters(openRow, {
				...DEFAULT_JOB_BOARD_FILTERS,
				provider: "greenhouse",
			}),
		).toBe(true);
		expect(
			jobMatchesFilters(openRow, {
				...DEFAULT_JOB_BOARD_FILTERS,
				provider: "lever",
			}),
		).toBe(false);
	});

	it("matches provider, location, department, team, employment, and skill fuzzily", () => {
		expect(
			jobMatchesFilters(openRow, {
				...DEFAULT_JOB_BOARD_FILTERS,
				provider: "grnhse",
				location: "sfo",
				department: "eng",
				team: "plat",
				employment: "ftime",
				skill: "kube",
			}),
		).toBe(true);
	});

	it("evaluates salary overlap with both bounds", () => {
		expect(salaryOverlaps(openRow, 150000, 200000)).toBe(true);
		expect(salaryOverlaps(openRow, 200000, null)).toBe(false);
	});

	it("rejects jobs with no salary when a salary filter is active", () => {
		expect(salaryOverlaps(makeRow({ salaryMin: null, salaryMax: null }), 100000, null)).toBe(
			false,
		);
	});

	it("does not treat null salary fields as zero", () => {
		const maxOnly = makeRow({ salaryMin: null, salaryMax: 160000 });
		expect(salaryOverlaps(maxOnly, 150000, null)).toBe(true);
		expect(salaryOverlaps(maxOnly, 170000, null)).toBe(false);
	});

	it("does not render null salaries as zero", () => {
		expect(formatSalary(makeRow({ salaryMin: null, salaryMax: null }))).toBe("");
		expect(formatSalary(makeRow({ salaryMin: null, salaryMax: 160000 }))).toBe(
			"Up to $160,000",
		);
		expect(formatSalary(makeRow({ salaryMin: 140000, salaryMax: null }))).toBe(
			"$140,000+",
		);
	});

	it("uses the populated salary bound when only one side exists", () => {
		const minOnly = makeRow({ salaryMin: 120000, salaryMax: null });
		expect(salaryOverlaps(minOnly, null, 130000)).toBe(true);
		expect(salaryOverlaps(minOnly, null, 110000)).toBe(false);
	});

	it("passes when no salary filter is provided", () => {
		expect(salaryOverlaps(makeRow({ salaryMin: null, salaryMax: null }), null, null)).toBe(
			true,
		);
	});

	it("evaluates skill and posted date ranges", () => {
		expect(skillMatches(openRow, "python")).toBe(true);
		expect(skillMatches(openRow, "rust")).toBe(false);
		expect(postedAtInRange(openRow, "2026-06-01", "2026-06-30")).toBe(true);
		expect(postedAtInRange(openRow, "2026-07-01", "")).toBe(false);
	});

	it("allows empty skill filter", () => {
		expect(skillMatches(openRow, "")).toBe(true);
	});

	it("matches query in title and company", () => {
		expect(queryMatches(openRow, "platform", false)).toBe(true);
		expect(queryMatches(openRow, "acme", false)).toBe(true);
		expect(queryMatches(openRow, "sales", false)).toBe(false);
	});

	it("matches wide query across department and provider", () => {
		expect(queryMatches(openRow, "engineering", true)).toBe(true);
		expect(queryMatches(openRow, "greenhouse", true)).toBe(true);
		expect(queryMatches(openRow, "marketing", true)).toBe(false);
	});

	it("scores title matches higher than incidental matches", () => {
		const titleHit = makeRow({ title: "Platform Lead" });
		const companyHit = makeRow({ title: "Analyst", company: "Platform Labs" });
		expect(relevanceScore(titleHit, ["platform"])).toBeGreaterThan(
			relevanceScore(companyHit, ["platform"]),
		);
	});

	it("sorts by relevance when query is present", () => {
		const rows = [
			makeRow({
				id: "low",
				title: "Sales Manager",
				syncedAt: "2026-06-20T10:00:00Z",
			}),
			makeRow({
				id: "high",
				title: "Platform Engineer",
				company: "Acme Platform",
				syncedAt: "2026-06-10T10:00:00Z",
			}),
		];
		const sorted = filterAndSortJobs(
			rows,
			{ ...DEFAULT_JOB_BOARD_FILTERS, query: "platform" },
			"relevance",
		);
		expect(sorted[0][J.id]).toBe("high");
	});

	it("sorts by latestObservedAt when query is empty", () => {
		const rows = [
			makeRow({
				id: "older",
				latestObserved: "2026-06-01T10:00:00Z",
				syncedAt: "2026-06-01T10:00:00Z",
			}),
			makeRow({
				id: "newer",
				latestObserved: "2026-06-20T10:00:00Z",
				syncedAt: "2026-06-20T10:00:00Z",
			}),
		];
		const sorted = filterAndSortJobs(rows, DEFAULT_JOB_BOARD_FILTERS, "latest");
		expect(sorted[0][J.id]).toBe("newer");
	});

	it("uses latestObservedAt instead of syncedAt for latest sorting", () => {
		const rows = [
			makeRow({
				id: "older-sync",
				latestObserved: "2026-06-01T10:00:00Z",
				syncedAt: "2026-06-20T10:00:00Z",
			}),
			makeRow({
				id: "newer-observed",
				latestObserved: "2026-06-20T10:00:00Z",
				syncedAt: "2026-06-01T10:00:00Z",
			}),
		];
		const sorted = filterAndSortJobs(rows, DEFAULT_JOB_BOARD_FILTERS, "latest");
		expect(sorted[0][J.id]).toBe("newer-observed");
	});

	it("sorts same-second mixed-precision latestObservedAt timestamps chronologically", () => {
		const rows = [
			makeRow({
				id: "whole-second",
				latestObserved: "2026-06-20T10:00:00Z",
			}),
			makeRow({
				id: "fractional-second",
				latestObserved: "2026-06-20T10:00:00.500000Z",
			}),
		];
		const sorted = filterAndSortJobs(rows, DEFAULT_JOB_BOARD_FILTERS, "latest");
		expect(sorted[0][J.id]).toBe("fractional-second");
	});

	it("uses latestObservedAt as relevance tie-breaker", () => {
		const rows = [
			makeRow({
				id: "older-hit",
				title: "Platform Engineer",
				latestObserved: "2026-06-01T10:00:00Z",
			}),
			makeRow({
				id: "newer-hit",
				title: "Platform Engineer",
				latestObserved: "2026-06-20T10:00:00Z",
			}),
		];
		const sorted = filterAndSortJobs(
			rows,
			{ ...DEFAULT_JOB_BOARD_FILTERS, query: "platform" },
			"relevance",
		);
		expect(sorted[0][J.id]).toBe("newer-hit");
	});

	it("filters by postedAfter and postedBefore independently", () => {
		expect(
			jobMatchesFilters(openRow, {
				...DEFAULT_JOB_BOARD_FILTERS,
				postedAfter: "2026-06-01",
			}),
		).toBe(true);
		expect(
			jobMatchesFilters(openRow, {
				...DEFAULT_JOB_BOARD_FILTERS,
				postedBefore: "2026-05-31",
			}),
		).toBe(false);
	});

	it("precomputes relevance scores at most once per filtered row", () => {
		const spy = vi.spyOn(searchJobCore, "relevanceScoreForJobRow");
		const rows = [
			makeRow({ id: "a", title: "Platform Engineer" }),
			makeRow({ id: "b", title: "Platform Lead" }),
			makeRow({ id: "c", title: "Sales Manager" }),
		];
		filterAndSortJobs(
			rows,
			{ ...DEFAULT_JOB_BOARD_FILTERS, query: "platform" },
			"relevance",
		);
		// All three rows match empty non-query filters; scoring is once per filtered row.
		expect(spy.mock.calls.length).toBeLessThanOrEqual(rows.length);
		expect(spy.mock.calls.length).toBeGreaterThan(0);
		spy.mockRestore();
	});
});
