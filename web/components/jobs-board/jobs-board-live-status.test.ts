import { describe, expect, it } from "vitest";

import { buildJobsBoardLiveStatus } from "./jobs-board-live-status";

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