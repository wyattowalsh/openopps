// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobsBoardEmpty } from "./jobs-board-empty";

afterEach(() => {
	cleanup();
});

describe("JobsBoardEmpty", () => {
	it("does not tell users to search before a loaded browse", () => {
		render(
			<JobsBoardEmpty
				matchCount={1234}
				activeFilterCount={0}
				onClearFilters={vi.fn()}
			/>,
		);

		expect(screen.getByText("No open jobs")).toBeTruthy();
		expect(
			screen.getByText("The current snapshot has no open roles to list."),
		).toBeTruthy();
		expect(screen.queryByText("Search or filter open jobs")).toBeNull();
		expect(screen.queryByText(/load a paginated result set/i)).toBeNull();
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
		expect(
			screen.getByRole("region", { name: "No open jobs match" }),
		).toBeTruthy();
		const clearFilters = screen.getByRole("button", { name: /clear filters/i });
		expect(clearFilters).toBeTruthy();
		expect(clearFilters.className).toMatch(/min-h-11/);
	});

	it("uses loading copy for the default browse instead of searching copy", () => {
		render(
			<JobsBoardEmpty
				matchCount={0}
				activeFilterCount={0}
				onClearFilters={vi.fn()}
				loadingResults
			/>,
		);

		expect(screen.getByText("Loading open jobs")).toBeTruthy();
		expect(screen.getByText("Fetching the latest open roles.")).toBeTruthy();
		expect(screen.queryByText("Searching open jobs")).toBeNull();
	});

	it("is not a polite live region; the board-level status announces instead", () => {
		const { container, rerender } = render(
			<JobsBoardEmpty
				matchCount={12}
				activeFilterCount={2}
				onClearFilters={vi.fn()}
			/>,
		);

		expect(container.querySelector("[aria-live]")).toBeNull();
		expect(screen.queryByRole("status")).toBeNull();
		expect(
			screen.getByRole("region", { name: "No open jobs match" }),
		).toBeTruthy();

		rerender(
			<JobsBoardEmpty
				matchCount={12}
				activeFilterCount={2}
				onClearFilters={vi.fn()}
				loadingResults
			/>,
		);

		expect(screen.getByText("Searching open jobs")).toBeTruthy();
		expect(container.querySelector("[aria-live]")).toBeNull();
		expect(screen.queryByRole("status")).toBeNull();
		expect(
			screen.getByRole("region", { name: "Searching open jobs" }),
		).toBeTruthy();
	});
});
