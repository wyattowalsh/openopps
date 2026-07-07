// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobsBoardEmpty } from "./jobs-board-empty";

afterEach(() => {
	cleanup();
});

describe("JobsBoardEmpty", () => {
	it("does not show a fake match count before a search or filter", () => {
		render(
			<JobsBoardEmpty
				matchCount={1234}
				activeFilterCount={0}
				onClearFilters={vi.fn()}
			/>,
		);

		expect(screen.getByText("No visible open jobs")).toBeTruthy();
		expect(screen.queryByText(/1,234 roles pass/i)).toBeNull();
		expect(screen.queryByRole("button", { name: /clear filters/i })).toBeNull();
	});

	it("shows match count context once filters are active", () => {
		render(
			<JobsBoardEmpty
				matchCount={12}
				activeFilterCount={2}
				onClearFilters={vi.fn()}
			/>,
		);

		expect(screen.getByText("No open jobs match")).toBeTruthy();
		expect(screen.getByText(/12 roles pass/i)).toBeTruthy();
		expect(screen.getByRole("button", { name: /clear filters/i })).toBeTruthy();
	});
});
