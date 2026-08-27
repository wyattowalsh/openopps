// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_EXPLORER_FILTERS } from "@/components/openopps-search/explorer-filter-engine";
import type { Entity, SearchManifest } from "@/components/openopps-search/search-types";

import { ExplorerToolbar } from "./explorer-toolbar";

afterEach(() => {
	cleanup();
});

const LONG_WORKPLACE = "On-site San Francisco Bay Area, California, USA";

const manifest: SearchManifest = {
	version: 6,
	snapshotAt: "2026-01-01T00:00:00Z",
	source: { database: "test", tables: [] },
	defaultEntity: "jobs",
	defaultFilters: { jobs: { status: "open" } },
	entities: {
		jobs: { columns: ["id"], count: 1 },
		boards: { columns: ["key"], count: 1 },
		providers: { columns: ["id"], count: 1 },
	},
	facets: {
		sources: ["manual"],
		providerIds: ["greenhouse"],
		jobStatuses: ["open"],
		supportLevels: ["full"],
		routeStatuses: ["ok"],
		workplaces: [LONG_WORKPLACE],
		employmentTypes: ["full-time"],
	},
};

function renderToolbar(entity: Entity) {
	return render(
		<ExplorerToolbar
			entity={entity}
			filters={DEFAULT_EXPLORER_FILTERS}
			manifest={manifest}
			sortKey={entity === "jobs" ? "latest" : entity === "boards" ? "name" : "provider"}
			matchCount={12}
			onFiltersChange={vi.fn()}
			onSortChange={vi.fn()}
			onClearFilters={vi.fn()}
		/>,
	);
}

function expectConstrainedSelect(name: string) {
	const select = screen.getByRole("combobox", { name });
	expect(select.classList.contains("w-full")).toBe(true);
	expect(select.classList.contains("min-w-0")).toBe(true);
	expect(select.classList.contains("max-w-full")).toBe(true);
	expect(select.classList.contains("overflow-hidden")).toBe(true);
	expect(select.classList.contains("text-ellipsis")).toBe(true);
	return select;
}

describe("ExplorerToolbar", () => {
	it("lets search wrap and shrink, and constrains Jobs selects including long Workplace options", () => {
		expect(LONG_WORKPLACE).toHaveLength(47);

		const { container } = renderToolbar("jobs");
		const toolbar = container.querySelector(".opps-toolbar");
		expect(toolbar).not.toBeNull();
		expect(toolbar?.classList.contains("min-w-0")).toBe(true);
		expect(toolbar?.className.includes("[&>*]:min-w-0")).toBe(true);

		const searchRow = toolbar?.children[0];
		expect(searchRow?.classList.contains("flex")).toBe(true);
		expect(searchRow?.classList.contains("flex-wrap")).toBe(true);
		expect(searchRow?.classList.contains("min-w-0")).toBe(true);
		expect(searchRow?.className.includes("[&>*]:min-w-0")).toBe(true);

		const search = screen.getByRole("textbox", { name: "Search dataset" });
		expect(search.getAttribute("placeholder")).toBe(
			"company, title, board, provider, route",
		);
		expect(search.classList.contains("w-full")).toBe(true);
		expect(search.classList.contains("min-w-0")).toBe(true);
		expect(search.classList.contains("max-w-full")).toBe(true);
		expect(search.parentElement?.classList.contains("min-w-0")).toBe(true);
		expect(search.parentElement?.classList.contains("basis-full")).toBe(true);
		expect(search.parentElement?.className.includes("sm:flex-1")).toBe(true);

		const filterGrid = toolbar?.children[1];
		expect(filterGrid?.classList.contains("min-w-0")).toBe(true);
		expect(filterGrid?.className.includes("[&>*]:min-w-0")).toBe(true);

		for (const name of ["Sort", "Source", "Provider", "Job status", "Workplace", "Employment"]) {
			expectConstrainedSelect(name);
		}

		expect(screen.getByRole("combobox", { name: "Workplace" }).textContent).toContain(
			LONG_WORKPLACE,
		);
		expect(screen.getByRole("textbox", { name: "Location" }).classList.contains("min-w-0")).toBe(
			true,
		);
	});

	it("omits Workplace on Boards and still constrains the remaining selects", () => {
		renderToolbar("boards");

		expect(screen.queryByRole("combobox", { name: "Workplace" })).toBeNull();
		expect(screen.queryByRole("combobox", { name: "Provider" })).toBeNull();
		expectConstrainedSelect("Sort");
		expectConstrainedSelect("Source");
		expect(screen.getByRole("textbox", { name: "Search dataset" }).classList.contains("min-w-0")).toBe(
			true,
		);
	});

	it("omits Workplace on Providers and still constrains the remaining selects", () => {
		renderToolbar("providers");

		expect(screen.queryByRole("combobox", { name: "Workplace" })).toBeNull();
		expectConstrainedSelect("Sort");
		expectConstrainedSelect("Source");
		expectConstrainedSelect("Provider");
		expectConstrainedSelect("Support");
		expectConstrainedSelect("Route status");
	});
});
