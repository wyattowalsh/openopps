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

		expect(screen.getByText("Search or filter open jobs")).toBeTruthy();
		expect(screen.getByText(/load a paginated result set from the server/i)).toBeTruthy();
		expect(screen.queryByText(/1,234 roles pass/i)).toBeNull();
		expect(screen.queryByRole("button", { name: /clear filters/i })).toBeNull();
	});

	it("shows match count context once filters are active", () => {
		const { container } = render(
			<JobsBoardEmpty
				matchCount={12}
				activeFilterCount={2}
				onClearFilters={vi.fn()}
			/>,
		);

		expect(container.textContent).toMatch(/No open jobs match/);
		expect(container.textContent).toMatch(/12 roles pass/i);
		expect(screen.getByRole("button", { name: /clear filters/i })).toBeTruthy();
	}, 15_000);
});
