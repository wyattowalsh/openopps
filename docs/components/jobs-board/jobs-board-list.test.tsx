// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
		fireEvent.keyDown(listbox, { key: "ArrowDown" });

		const firstOption = screen.getByRole("option", {
			name: "Engineer at Acme",
		});
		expect(listbox.getAttribute("aria-activedescendant")).toBe(firstOption.id);
		expect(firstOption.getAttribute("aria-posinset")).toBe("1");
		expect(firstOption.getAttribute("aria-setsize")).toBe("2");

		fireEvent.keyDown(listbox, { key: "End" });
		const secondOption = screen.getByRole("option", {
			name: "Designer at Acme",
		});
		expect(listbox.getAttribute("aria-activedescendant")).toBe(secondOption.id);

		fireEvent.keyDown(listbox, { key: "Enter" });
		expect(onSelectJob).toHaveBeenCalledWith("job-2");
	}, 15_000);
});

function row(id: string, title: string): SearchRow {
	const values = Array.from({ length: 28 }, () => null) as SearchRow;
	values[J.id] = id;
	values[J.title] = title;
	values[J.company] = "Acme";
	values[J.locations] = "Remote";
	return values;
}
