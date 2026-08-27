// @vitest-environment jsdom

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SearchManifest } from "@/components/openopps-search/search-types";

import { JobsBoardMetrics } from "./jobs-board-metrics";

vi.mock("next/link", () => ({
	default: ({ children, href }: { children: React.ReactNode; href: string }) => (
		<a href={href}>{children}</a>
	),
}));

afterEach(() => {
	cleanup();
});

describe("JobsBoardMetrics", () => {
	it("does not present unfiltered open jobs as matches while a search is in flight", () => {
		const { container } = render(
			<JobsBoardMetrics
				manifest={manifest({ openJobCount: 88800 })}
				matchCount={null}
				searchActive
			/>,
		);

		expect(metricMap(container)).toEqual({
			matches: "—",
			"open jobs": "88,800",
			"indexed jobs": "90,000",
			routes: "120",
		});
	});

	it("shows the search total once matches arrive", () => {
		const { container } = render(
			<JobsBoardMetrics
				manifest={manifest({ openJobCount: 88800 })}
				matchCount={40}
				searchActive
			/>,
		);

		expect(metricMap(container).matches).toBe("40");
		expect(metricMap(container)["open jobs"]).toBe("88,800");
	});

	it("keeps the open-jobs strip when search is idle", () => {
		const { container } = render(
			<JobsBoardMetrics
				manifest={manifest({ openJobCount: 88800 })}
				matchCount={88800}
				searchActive={false}
			/>,
		);

		expect(metricMap(container)).toEqual({
			"open jobs": "88,800",
			"indexed jobs": "90,000",
			sources: "700",
			routes: "120",
		});
	});
});

function metricMap(container: HTMLElement): Record<string, string> {
	const metrics = [...container.querySelectorAll(".opps-metric")];
	return Object.fromEntries(
		metrics.map((metric) => {
			const value = metric.querySelector(".font-heading")?.textContent?.trim() ?? "";
			const label = metric.querySelector(".font-mono")?.textContent?.trim() ?? "";
			return [label, value];
		}),
	);
}

function manifest({ openJobCount }: { openJobCount: number }): SearchManifest {
	return {
		version: 6,
		snapshotAt: null,
		openJobCount,
		counts: {
			snapshot: {
				database: "kaggle/openoppsdb.sqlite",
				sourceRows: 700,
				providerRoutes: 120,
				boards: 10,
				jobs: 90000,
				openJobs: openJobCount,
			},
		},
		source: {
			database: "kaggle/openoppsdb.sqlite",
			tables: ["jobs"],
		},
		defaultEntity: "jobs",
		defaultFilters: { jobs: { status: "open" } },
		entities: {
			jobs: { count: 90000, columns: [] },
			boards: { count: 10, columns: [] },
			providers: { count: 120, columns: [] },
		},
		facets: {
			sources: [],
			providerIds: [],
			jobStatuses: [],
			supportLevels: [],
			routeStatuses: [],
			workplaces: [],
			employmentTypes: [],
		},
	} as unknown as SearchManifest;
}
