import { describe, expect, it } from "vitest";

import {
	EXPLORER_FILTER_DEBOUNCE_MS,
	explorerFilterQueryOptions,
	filtersFromExplorerQuery,
	pageFromVisibleLimit,
	parseExplorerEntity,
	resolveExplorerSortKey,
	visibleLimitFromPage,
} from "./explorer-filter-state";

describe("explorer filter URL state", () => {
	it("maps query state to explorer filters", () => {
		expect(
			filtersFromExplorerQuery({
				entity: "jobs",
				q: "platform",
				source: "a16z",
				provider: "greenhouse",
				jobStatus: "open",
				support: "",
				routeStatus: "",
				workplace: "remote",
				employment: "full-time",
				location: "sf",
				sort: "latest",
				page: 2,
			}),
		).toEqual({
			query: "platform",
			source: "a16z",
			provider: "greenhouse",
			jobStatus: "open",
			support: "",
			routeStatus: "",
			workplace: "remote",
			employment: "full-time",
			location: "sf",
		});
	});

	it("falls back to jobs for unknown entities", () => {
		expect(parseExplorerEntity("unknown")).toBe("jobs");
		expect(parseExplorerEntity("boards")).toBe("boards");
	});

	it("resolves sort keys per entity with defaults", () => {
		expect(resolveExplorerSortKey("jobs", "company")).toBe("company");
		expect(resolveExplorerSortKey("jobs", "invalid")).toBe("latest");
		expect(resolveExplorerSortKey("boards", "invalid")).toBe("name");
	});

	it("converts page and visible limits using PAGE_SIZE", () => {
		expect(visibleLimitFromPage(1)).toBe(50);
		expect(visibleLimitFromPage(2)).toBe(100);
		expect(pageFromVisibleLimit(50)).toBe(1);
		expect(pageFromVisibleLimit(75)).toBe(2);
	});

	it("debounces live filter URL updates", () => {
		expect(EXPLORER_FILTER_DEBOUNCE_MS).toBe(200);
		expect(explorerFilterQueryOptions).toMatchObject({
			history: "replace",
			shallow: true,
			clearOnDefault: true,
		});
	});
});
