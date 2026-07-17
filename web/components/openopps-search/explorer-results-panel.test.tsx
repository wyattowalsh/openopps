// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExplorerResultsPanel } from "./explorer-results-panel";
import type { SearchRow } from "@/components/openopps-search/search-types";

afterEach(() => {
	cleanup();
});

describe("ExplorerResultsPanel", () => {
	it("keeps pagination outside the results list landmark", () => {
		const { container } = render(
			<ExplorerResultsPanel
				entity="jobs"
				rows={[jobRow("Designer")]}
				total={1}
				visibleLimit={50}
				onMore={() => {}}
			/>,
		);

		const list = container.querySelector('[role="list"]');
		expect(list).not.toBeNull();
		expect(list?.querySelector("button")).toBeNull();
	}, 15_000);

	it("omits unsafe outbound links", () => {
		render(
			<ExplorerResultsPanel
				entity="jobs"
				rows={[jobRow("Designer", "javascript:alert(1)")] }
				total={1}
				visibleLimit={50}
				onMore={() => {}}
			/>,
		);

		expect(screen.queryByRole("link", { name: /open posting/i })).toBeNull();
	});

	it("activates the focused posting link on Enter", () => {
		const clickSpy = vi
			.spyOn(HTMLAnchorElement.prototype, "click")
			.mockImplementation(() => {});

		render(
			<ExplorerResultsPanel
				entity="jobs"
				rows={[jobRow("Designer")]}
				total={1}
				visibleLimit={50}
				onMore={() => {}}
			/>,
		);

		const list = screen.getByRole("list", { name: /jobs results/i });
		list.focus();
		fireEvent.keyDown(list, { key: "ArrowDown" });
		fireEvent.keyDown(screen.getByRole("listitem"), { key: "Enter" });

		expect(clickSpy).toHaveBeenCalled();
		clickSpy.mockRestore();
	}, 15_000);
});

function jobRow(title: string, url = "https://example.test/jobs/1"): SearchRow {
	return [
		`job-${title}`,
		"manual",
		"manual:acme",
		"greenhouse",
		"open",
		title,
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
		url,
		"2026-01-01",
		"2026-01-01",
		'["manual"]',
		"",
		"",
		"2026-01-01",
	];
}
