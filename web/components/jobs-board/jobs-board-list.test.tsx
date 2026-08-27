// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobsBoardList } from "./jobs-board-list";
import type { SearchRow } from "@/components/openopps-search/search-types";
import { J } from "@/components/openopps-search/search-utils";

vi.mock("@tanstack/react-virtual", () => ({
	useVirtualizer: ({
		count,
		estimateSize,
	}: {
		count: number;
		estimateSize: () => number;
	}) => ({
		getTotalSize: () => count * estimateSize(),
		getVirtualItems: () =>
			Array.from({ length: count }, (_, index) => ({
				index,
				key: index,
				size: estimateSize(),
				start: index * estimateSize(),
			})),
		scrollToIndex: () => undefined,
	}),
}));

afterEach(() => {
	cleanup();
});

describe("JobsBoardList", () => {
	it("exposes listbox option semantics and active descendant keyboard state", () => {
		const onSelectJob = vi.fn();
		render(
			<JobsBoardList
				rows={[row("job-1", "Engineer"), row("job-2", "Designer")]}
				selectedJobId=""
				onSelectJob={onSelectJob}
			/>,
		);

		const listbox = screen.getByRole("listbox", { name: "Open jobs results" });
		expect(listbox.getAttribute("aria-orientation")).toBe("vertical");
		fireEvent.keyDown(listbox, { key: "ArrowDown" });

		const options = screen.getAllByRole("option");
		const firstOption = options[0];
		const secondOption = options[1];
		expect(firstOption.getAttribute("aria-label")).toBeNull();
		expect(firstOption.textContent).toMatch(/Engineer/);
		expect(firstOption.textContent).toMatch(/Acme/);
		expect(listbox.getAttribute("aria-activedescendant")).toBe(firstOption.id);
		expect(firstOption.getAttribute("aria-posinset")).toBe("1");
		expect(firstOption.getAttribute("aria-setsize")).toBe("2");

		fireEvent.keyDown(listbox, { key: "End" });
		expect(listbox.getAttribute("aria-activedescendant")).toBe(secondOption.id);

		fireEvent.keyDown(listbox, { key: "Enter" });
		expect(onSelectJob).toHaveBeenCalledWith("job-2");

		onSelectJob.mockClear();
		fireEvent.keyDown(listbox, { key: " " });
		expect(onSelectJob).toHaveBeenCalledWith("job-2");
	}, 15_000);

	it("selects a row on click and keeps listbox focus", async () => {
		const user = userEvent.setup();
		const onSelectJob = vi.fn();
		render(
			<JobsBoardList
				rows={[row("job-1", "Engineer"), row("job-2", "Designer")]}
				selectedJobId=""
				onSelectJob={onSelectJob}
			/>,
		);

		const listbox = screen.getByRole("listbox", { name: "Open jobs results" });
		const firstOption = screen.getAllByRole("option")[0];
		await user.click(firstOption);
		expect(onSelectJob).toHaveBeenCalledWith("job-1");
		expect(document.activeElement).toBe(listbox);
		expect(firstOption.getAttribute("aria-label")).toBeNull();
	});

	it("selects a row on mousedown so Chromium clicks are not swallowed", () => {
		const onSelectJob = vi.fn();
		render(
			<JobsBoardList
				rows={[row("job-1", "Engineer"), row("job-2", "Designer")]}
				selectedJobId=""
				onSelectJob={onSelectJob}
			/>,
		);

		const listbox = screen.getByRole("listbox", { name: "Open jobs results" });
		const firstOption = screen.getAllByRole("option")[0];
		fireEvent.mouseDown(firstOption);
		expect(onSelectJob).toHaveBeenCalledWith("job-1");
		expect(document.activeElement).toBe(listbox);
	});

	it("drops the landing min-height when filling a split pane", () => {
		render(
			<JobsBoardList
				rows={[row("job-1", "Engineer")]}
				selectedJobId="job-1"
				onSelectJob={vi.fn()}
				fillHeight
			/>,
		);

		const listbox = screen.getByRole("listbox", { name: "Open jobs results" });
		expect(listbox.className).toContain("min-h-0");
		expect(listbox.className).not.toContain("min-h-[24rem]");
		expect(listbox.className).not.toContain("lg:min-h-[32rem]");
	});
});

function row(id: string, title: string): SearchRow {
	const values = Array.from({ length: 28 }, () => null) as SearchRow;
	values[J.id] = id;
	values[J.title] = title;
	values[J.company] = "Acme";
	values[J.locations] = "Remote";
	return values;
}
