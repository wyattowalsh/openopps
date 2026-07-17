import { describe, expect, it } from "vitest";

import { DEFAULT_EXPLORER_SORT } from "./explorer-filter-engine";
import { shouldLoadFullJobsIndexForExplorer } from "./explorer-load-state";

describe("explorer full jobs load state", () => {
	const baseDecision = {
		entity: "jobs" as const,
		hasJobsChunk: true,
		fullJobsLoaded: false,
		fullJobsRequested: false,
		fullJobsError: null,
		activeFilterCount: 0,
		sortKey: DEFAULT_EXPLORER_SORT.jobs,
		defaultJobsSort: DEFAULT_EXPLORER_SORT.jobs,
	};

	it("does not load the full jobs index outside the jobs entity", () => {
		expect(
			shouldLoadFullJobsIndexForExplorer({
				...baseDecision,
				entity: "boards",
				activeFilterCount: 1,
			}),
		).toBe(false);
	});

	it("does not load before the initial jobs chunk exists", () => {
		expect(
			shouldLoadFullJobsIndexForExplorer({
				...baseDecision,
				hasJobsChunk: false,
				fullJobsRequested: true,
			}),
		).toBe(false);
	});

	it("does not load for the default latest jobs view", () => {
		expect(shouldLoadFullJobsIndexForExplorer(baseDecision)).toBe(false);
	});

	it("loads when filters are active", () => {
		expect(
			shouldLoadFullJobsIndexForExplorer({
				...baseDecision,
				activeFilterCount: 1,
			}),
		).toBe(true);
	});

	it("loads after an explicit full-index request", () => {
		expect(
			shouldLoadFullJobsIndexForExplorer({
				...baseDecision,
				fullJobsRequested: true,
			}),
		).toBe(true);
	});

	it("loads for non-default jobs sorting", () => {
		expect(
			shouldLoadFullJobsIndexForExplorer({
				...baseDecision,
				sortKey: "company",
			}),
		).toBe(true);
	});

	it("does not load after the full jobs index is already loaded", () => {
		expect(
			shouldLoadFullJobsIndexForExplorer({
				...baseDecision,
				fullJobsLoaded: true,
				activeFilterCount: 1,
				fullJobsRequested: true,
			}),
		).toBe(false);
	});

	it("blocks automatic reload after a full-index error", () => {
		expect(
			shouldLoadFullJobsIndexForExplorer({
				...baseDecision,
				fullJobsError: "Unable to load jobs.",
				activeFilterCount: 1,
				fullJobsRequested: true,
			}),
		).toBe(false);
	});

	it("permits retry when the full-index error is cleared", () => {
		expect(
			shouldLoadFullJobsIndexForExplorer({
				...baseDecision,
				fullJobsError: null,
				fullJobsRequested: true,
			}),
		).toBe(true);
	});
});
