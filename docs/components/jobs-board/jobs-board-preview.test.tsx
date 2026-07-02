// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobsBoardPreview } from "./jobs-board-preview";
import type { SearchRow } from "@/components/openopps-search/search-types";

afterEach(() => {
	cleanup();
});

describe("JobsBoardPreview", () => {
	it("gives the desktop close control a specific accessible name", () => {
		render(
			<JobsBoardPreview
				row={jobRow()}
				selectedJobId="job-1"
				detail={null}
				loading={false}
				error={null}
				onClose={vi.fn()}
			/>,
		);

		expect(
			screen.getByRole("button", { name: /close job preview/i }),
		).toBeTruthy();
	});
});

function jobRow(): SearchRow {
	return [
		"job-1",
		"manual",
		"manual:acme",
		"greenhouse",
		"open",
		"Designer",
		"Acme",
		"",
		"",
		"remote",
		"remote",
		"full-time",
		"[]",
		null,
		null,
		null,
		"https://example.test/jobs/1",
		"2026-01-01",
		"2026-01-01",
		'["manual"]',
		"",
		"",
		"2026-01-01",
	];
}
