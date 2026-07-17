import { describe, expect, it } from "vitest";

import {
	JOBS_BOARD_PREVIEW_SHEET_TITLE_ID,
	getJobsBoardPreviewSheetDialogProps,
	resolvePreviewSheetTabMove,
	shouldCloseJobsBoardPreviewSheet,
} from "./jobs-board-preview-sheet";

describe("jobs board preview sheet accessibility", () => {
	it("uses a stable accessible dialog name", () => {
		expect(getJobsBoardPreviewSheetDialogProps()).toEqual({
			role: "dialog",
			"aria-modal": true,
			"aria-labelledby": JOBS_BOARD_PREVIEW_SHEET_TITLE_ID,
		});
		expect(JOBS_BOARD_PREVIEW_SHEET_TITLE_ID).toBe(
			"openopps-jobs-preview-sheet-title",
		);
	});

	it("closes from Escape only", () => {
		expect(shouldCloseJobsBoardPreviewSheet("Escape")).toBe(true);
		expect(shouldCloseJobsBoardPreviewSheet("Esc")).toBe(false);
		expect(shouldCloseJobsBoardPreviewSheet("Tab")).toBe(false);
	});

	it("keeps Tab focus inside the sheet", () => {
		expect(
			resolvePreviewSheetTabMove({
				activeIndex: 0,
				focusableCount: 3,
				shiftKey: true,
			}),
		).toBe("last");
		expect(
			resolvePreviewSheetTabMove({
				activeIndex: 2,
				focusableCount: 3,
				shiftKey: false,
			}),
		).toBe("first");
		expect(
			resolvePreviewSheetTabMove({
				activeIndex: 1,
				focusableCount: 3,
				shiftKey: false,
			}),
		).toBe("none");
	});

	it("recovers focus when the active element is outside the sheet", () => {
		expect(
			resolvePreviewSheetTabMove({
				activeIndex: -1,
				focusableCount: 2,
				shiftKey: false,
			}),
		).toBe("first");
		expect(
			resolvePreviewSheetTabMove({
				activeIndex: -1,
				focusableCount: 2,
				shiftKey: true,
			}),
		).toBe("last");
		expect(
			resolvePreviewSheetTabMove({
				activeIndex: -1,
				focusableCount: 0,
				shiftKey: false,
			}),
		).toBe("dialog");
	});
});
