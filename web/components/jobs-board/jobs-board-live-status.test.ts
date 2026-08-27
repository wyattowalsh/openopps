import { describe, expect, it } from "vitest";

import {
	buildJobsBoardLiveStatus,
	jobsBoardDesktopPreviewClassName,
	jobsBoardLedgerClassName,
	jobsBoardResultsFrameClassName,
	jobsBoardSectionClassName,
	jobsBoardSplitColumnClassName,
	jobsBoardSplitGridClassName,
	jobsBoardSplitListPaneClassName,
	resolveJobsBoardMatchDisplay,
} from "./jobs-board-live-status";

describe("buildJobsBoardLiveStatus", () => {
	it("prioritizes manifest loading and errors", () => {
		expect(
			buildJobsBoardLiveStatus({
				manifestLoading: true,
				manifestError: null,
				searchLoading: true,
				searchActive: true,
				searchError: "search failed",
				indexNote: "note",
			}),
		).toBe("Loading open jobs index.");

		expect(
			buildJobsBoardLiveStatus({
				manifestLoading: false,
				manifestError: "Index unavailable",
				searchLoading: true,
				searchActive: true,
				searchError: null,
				indexNote: null,
			}),
		).toBe("Index unavailable");
	});

	it("announces search activity and falls back to index note", () => {
		expect(
			buildJobsBoardLiveStatus({
				manifestLoading: false,
				manifestError: null,
				searchLoading: true,
				searchActive: false,
				searchError: null,
				indexNote: null,
			}),
		).toBe("Loading open jobs.");

		expect(
			buildJobsBoardLiveStatus({
				manifestLoading: false,
				manifestError: null,
				searchLoading: false,
				searchActive: true,
				searchError: "Timed out",
				indexNote: "Showing page 1 of 2.",
			}),
		).toBe("Timed out");

		expect(
			buildJobsBoardLiveStatus({
				manifestLoading: false,
				manifestError: null,
				searchLoading: false,
				searchActive: false,
				searchError: null,
				indexNote: "Enter a search or use filters to browse the indexed jobs.",
			}),
		).toBe("Enter a search or use filters to browse the indexed jobs.");
	});
});

describe("resolveJobsBoardMatchDisplay", () => {
	it("keeps the unfiltered fallback as open jobs when search is idle", () => {
		expect(
			resolveJobsBoardMatchDisplay({
				searchActive: false,
				searchLoading: false,
				totalMatches: undefined,
				fallbackCount: 88800,
			}),
		).toEqual({ matchCount: 88800, showAsMatches: false });
	});

	it("does not treat unfiltered open jobs as matches while search is in flight", () => {
		expect(
			resolveJobsBoardMatchDisplay({
				searchActive: true,
				searchLoading: true,
				totalMatches: undefined,
				fallbackCount: 88800,
			}),
		).toEqual({ matchCount: null, showAsMatches: true });
	});

	it("uses the search total once it arrives, including during a later reload", () => {
		expect(
			resolveJobsBoardMatchDisplay({
				searchActive: true,
				searchLoading: false,
				totalMatches: 40,
				fallbackCount: 88800,
			}),
		).toEqual({ matchCount: 40, showAsMatches: true });

		expect(
			resolveJobsBoardMatchDisplay({
				searchActive: true,
				searchLoading: true,
				totalMatches: 40,
				fallbackCount: 88800,
			}),
		).toEqual({ matchCount: 40, showAsMatches: true });
	});

	it("hides match totals after a failed search with no meta", () => {
		expect(
			resolveJobsBoardMatchDisplay({
				searchActive: true,
				searchLoading: false,
				totalMatches: null,
				fallbackCount: 88800,
			}),
		).toEqual({ matchCount: null, showAsMatches: true });
	});
});

describe("jobs board desktop split layout", () => {
	it("caps the selected-job split to the viewport minus home nav on lg+", () => {
		const section = jobsBoardSectionClassName(true);
		expect(section).toContain("lg:h-[calc(100dvh-3.5rem)]");
		expect(section).toContain("lg:max-h-[calc(100dvh-3.5rem)]");
		expect(section).toContain("lg:min-h-0");
		expect(section).toContain("lg:overflow-hidden");
		expect(section).not.toMatch(/(?:^|\s)h-\[calc/);
		expect(section).not.toMatch(/(?:^|\s)overflow-hidden(?:\s|$)/);

		expect(jobsBoardLedgerClassName(true)).toContain("min-h-0");
		expect(jobsBoardLedgerClassName(true)).toContain("overflow-hidden");
		expect(jobsBoardResultsFrameClassName(true)).toContain("min-h-0");
		expect(jobsBoardSplitGridClassName(true)).toContain("min-h-0");
		expect(jobsBoardSplitGridClassName(true)).toContain("overflow-hidden");
		expect(jobsBoardSplitGridClassName(true)).toContain(
			"lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]",
		);
		expect(jobsBoardSplitColumnClassName(true)).toContain("min-h-0");
		expect(jobsBoardSplitListPaneClassName()).toContain("min-h-0");
		expect(jobsBoardSplitListPaneClassName()).toContain("[&>div]:min-h-0");

		const preview = jobsBoardDesktopPreviewClassName();
		expect(preview).toContain("hidden");
		expect(preview).toContain("lg:flex");
		expect(preview).toContain("lg:flex-col");
		expect(preview).toContain("min-h-0");
		expect(preview).toContain("overflow-hidden");
		expect(preview).toContain("[&>article]:min-h-0");
		expect(preview).toContain("[&>article]:flex-1");
	});

	it("does not cap the results layout when no job is selected", () => {
		expect(jobsBoardSectionClassName(false)).not.toContain("lg:h-[calc");
		expect(jobsBoardLedgerClassName(false)).toBe("opps-ledger-shell");
		expect(jobsBoardSplitGridClassName(false)).toBe("grid gap-4");
		expect(jobsBoardSplitColumnClassName(false)).toBe("grid gap-3");
	});
});
