// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobsBoardPreviewSheet } from "./jobs-board-preview-sheet";
import type { SearchRow } from "@/components/openopps-search/search-types";

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

describe("JobsBoardPreviewSheet scroll chain", () => {
	it("keeps flex children shrinkable so the nested preview pane can scroll", () => {
		stubMatchMedia(true);

		render(
			<JobsBoardPreviewSheet
				open
				row={jobRow()}
				selectedJobId="job-1"
				detail={{
					id: "job-1",
					status: "open",
					title: "Designer",
					company: "Acme",
					description: `${"Long posting description. ".repeat(80)}End of description.`,
					skills: [{ name: "TypeScript" }, { name: "Design systems" }],
				}}
				loading={false}
				error={null}
				onClose={vi.fn()}
			/>,
		);

		const dialog = screen.getByRole("dialog", { name: /job preview/i });
		expectClassTokens(dialog, [
			"flex",
			"max-h-[88vh]",
			"min-h-0",
			"flex-col",
			"overflow-hidden",
		]);

		const article = screen.getByRole("article");
		const sheetBody = article.parentElement;
		expect(sheetBody).not.toBeNull();
		expectClassTokens(sheetBody!, [
			"flex",
			"min-h-0",
			"flex-1",
			"flex-col",
			"overflow-hidden",
		]);

		expectClassTokens(article, [
			"flex",
			"h-full",
			"min-h-0",
			"flex-1",
			"flex-col",
			"overflow-hidden",
		]);
		expect(classTokens(article.className).has("min-h-[24rem]")).toBe(false);

		const scroller = Array.from(article.children).find((child) =>
			classTokens(child.className).has("overflow-y-auto"),
		);
		expect(scroller).not.toBeNull();
		expectClassTokens(scroller!, ["min-h-0", "flex-1", "overflow-y-auto"]);
		expect(scroller!.textContent).toContain("End of description.");
		expect(scroller!.textContent).toContain("TypeScript");
		expect(scroller!.textContent).toContain("Design systems");
	}, 15_000);

	it("does not render the mobile sheet on large viewports", () => {
		stubMatchMedia(false);

		render(
			<JobsBoardPreviewSheet
				open
				row={jobRow()}
				selectedJobId="job-1"
				detail={null}
				loading={false}
				error={null}
				onClose={vi.fn()}
			/>,
		);

		expect(screen.queryByRole("dialog")).toBeNull();
	}, 15_000);
});

function stubMatchMedia(matches: boolean) {
	vi.stubGlobal(
		"matchMedia",
		vi.fn((query: string) => ({
			matches,
			media: query,
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn(),
		})),
	);
}

function classTokens(className: string) {
	return new Set(className.split(/\s+/).filter(Boolean));
}

function expectClassTokens(element: Element, tokens: string[]) {
	const actual = classTokens(element.className);
	for (const token of tokens) {
		expect(actual.has(token)).toBe(true);
	}
}

function jobRow(url = "https://example.test/jobs/1"): SearchRow {
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
		url,
		"2026-01-01",
		"2026-01-01",
		'["manual"]',
		"",
		"",
		"2026-01-01",
	];
}
