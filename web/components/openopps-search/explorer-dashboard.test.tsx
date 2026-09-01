// @vitest-environment jsdom

import type { ReactElement } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { withNuqsTestingAdapter } from "nuqs/adapters/testing";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExplorerDashboard } from "./explorer-dashboard";
import { loadInitialJobsChunk } from "./search-index-loader";
import type { LineageAggregate, SearchChunk, SearchManifest, SearchRow } from "./search-types";
import { SEARCH_VERSION } from "./search-utils";

vi.mock("./search-index-loader", () => ({
	loadInitialJobsChunk: vi.fn(),
}));

vi.mock("next/link", () => ({
	default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
		<a href={href} {...props}>
			{children}
		</a>
	),
}));

afterEach(() => {
	cleanup();
});

beforeEach(() => {
	vi.mocked(loadInitialJobsChunk).mockReset();
	vi.mocked(loadInitialJobsChunk).mockResolvedValue(emptyJobsChunk());
});

describe("ExplorerDashboard", () => {
	it("renders full source-provider-board-job lineage analysis", async () => {
		renderDashboard(
			<ExplorerDashboard
				manifest={null}
				lineage={lineageAggregate}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);

		expect(await screen.findByText("Full lineage map", {}, { timeout: 5000 })).not.toBeNull();
		expect(screen.getByText("Source-provider routes")).not.toBeNull();
		expect(screen.getByText("Source-board reach")).not.toBeNull();
		expect(screen.getByText("Board job paths")).not.toBeNull();
		expect(screen.getByText("a16z -> greenhouse -> a16z:acme")).not.toBeNull();
		expect(screen.getByText("12 / 15 open")).not.toBeNull();
	}, 15_000);

	it("defers heavy lineage until the map is near the viewport", async () => {
		const callbacks: IntersectionObserverCallback[] = [];
		class FakeIntersectionObserver {
			constructor(callback: IntersectionObserverCallback) {
				callbacks.push(callback);
			}
			disconnect() {}
			observe() {}
			takeRecords(): IntersectionObserverEntry[] {
				return [];
			}
			unobserve() {}
		}
		vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
		vi.stubGlobal("requestIdleCallback", undefined);

		try {
			renderDashboard(
				<ExplorerDashboard
					manifest={null}
					lineage={lineageAggregate}
					loading={false}
					onInspectRows={() => {}}
				/>,
			);
			expect(screen.queryByText("Full lineage map")).toBeNull();
			expect(callbacks.length).toBeGreaterThan(0);
			callbacks[0]?.(
				[{ isIntersecting: true } as IntersectionObserverEntry],
				{} as IntersectionObserver,
			);
			expect(await screen.findByText("Full lineage map", {}, { timeout: 5000 })).not.toBeNull();
		} finally {
			vi.unstubAllGlobals();
		}
	});

	it("keeps the 13MB lineage aggregate off dashboard first paint", () => {
		renderDashboard(
			<ExplorerDashboard
				manifest={null}
				lineage={null}
				lineageDeferred
				loading={false}
				onInspectRows={() => {}}
			/>,
		);
		expect(screen.getByText("Lineage waits for inspect")).not.toBeNull();
		expect(screen.queryByText("Full lineage map")).toBeNull();
		expect(screen.queryByText("Lineage not in this snapshot")).toBeNull();
	});

	it("uses a ruled stage strip instead of nested lineage cards", async () => {
		renderDashboard(
			<ExplorerDashboard
				manifest={null}
				lineage={lineageAggregate}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);
		expect(await screen.findByText("Source rows", {}, { timeout: 5000 })).not.toBeNull();
		const stage = screen.getByText("Source rows").parentElement;
		expect(stage?.className).not.toContain("bg-card");
		expect(screen.getByText("Provider routes")).not.toBeNull();
	});

	it("reserves coverage and latest-jobs slots while the manifest is loading", () => {
		const { container } = renderDashboard(
			<ExplorerDashboard
				manifest={null}
				lineage={null}
				loading={true}
				onInspectRows={() => {}}
			/>,
		);
		expect(screen.getByText("Source coverage")).not.toBeNull();
		expect(screen.getByText("Latest open jobs")).not.toBeNull();
		expect(screen.queryByText("Latest open jobs are not in this snapshot yet.")).toBeNull();
		expect(screen.queryByText("Lineage not in this snapshot")).toBeNull();
		const reserved = [...container.querySelectorAll("ul")].filter((node) =>
			(node.getAttribute("style") ?? "").includes("min-height"),
		);
		expect(reserved.length).toBeGreaterThan(3);
	});

	it("renders ranked coverage bars for top sources, providers, and locations", () => {
		const { container } = renderDashboard(
			<ExplorerDashboard
				manifest={dashboardManifest()}
				lineage={null}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);
		expect(screen.getByText("Source coverage")).not.toBeNull();
		expect(screen.getByText("Provider coverage")).not.toBeNull();
		expect(screen.getByText("Locations")).not.toBeNull();
		expect(screen.getByRole("button", { name: "Inspect jobs for a16z" })).not.toBeNull();
		expect(
			screen.getByRole("button", { name: "Inspect jobs for greenhouse" }),
		).not.toBeNull();
		expect(screen.getByRole("button", { name: "Inspect jobs for Remote" })).not.toBeNull();
		expect(container.querySelector(".rounded-full")).toBeNull();
		expect(screen.getAllByText("01").length).toBeGreaterThan(0);
		expect(screen.getAllByText("80% open").length).toBeGreaterThan(0);
	});

	it("opens inspect rows with a source facet the inspector already supports", () => {
		const onInspectRows = vi.fn();
		const onInspectFacet = vi.fn();
		renderDashboard(
			<ExplorerDashboard
				manifest={dashboardManifest()}
				lineage={null}
				loading={false}
				onInspectRows={onInspectRows}
				onInspectFacet={onInspectFacet}
			/>,
		);
		fireEvent.click(screen.getByRole("button", { name: "Inspect jobs for a16z" }));
		expect(onInspectFacet).toHaveBeenCalledWith({
			entity: "jobs",
			filters: { source: "a16z" },
		});
		expect(onInspectRows).toHaveBeenCalledTimes(1);
	});

	it("inspects providers from route-health rows with a labeled status badge", () => {
		const onInspectFacet = vi.fn();
		renderDashboard(
			<ExplorerDashboard
				manifest={dashboardManifest()}
				lineage={null}
				loading={false}
				onInspectRows={vi.fn()}
				onInspectFacet={onInspectFacet}
			/>,
		);
		const support = screen.getByRole("button", { name: "Inspect providers for full" });
		expect(support.querySelector(".openopps-status-chip")?.textContent).toBe("full");
		fireEvent.click(support);
		expect(onInspectFacet).toHaveBeenCalledWith({
			entity: "providers",
			filters: { support: "full" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Inspect providers for error" }));
		expect(onInspectFacet).toHaveBeenCalledWith({
			entity: "providers",
			filters: { routeStatus: "error" },
		});
	});

	it("inspects lineage paths with source and provider filters", async () => {
		const onInspectFacet = vi.fn();
		renderDashboard(
			<ExplorerDashboard
				manifest={dashboardManifest()}
				lineage={lineageAggregate}
				loading={false}
				onInspectRows={vi.fn()}
				onInspectFacet={onInspectFacet}
			/>,
		);
		fireEvent.click(
			await screen.findByRole(
				"button",
				{ name: "Inspect lineage path a16z -> greenhouse -> a16z:acme" },
				{ timeout: 5000 },
			),
		);
		expect(onInspectFacet).toHaveBeenCalledWith({
			entity: "jobs",
			filters: { source: "a16z", provider: "greenhouse" },
		});
	});

	it("deep-links departments, companies, and skills to the jobs board because inspect has no those facets", () => {
		renderDashboard(
			<ExplorerDashboard
				manifest={dashboardManifest()}
				lineage={null}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);
		expect(
			screen.getByRole("link", { name: "Open Engineering on jobs board" }).getAttribute("href"),
		).toBe("/?department=Engineering");
		expect(screen.getByRole("link", { name: "Open Acme on jobs board" }).getAttribute("href")).toBe(
			"/?q=Acme",
		);
		expect(
			screen.getByRole("link", { name: "Open python on jobs board" }).getAttribute("href"),
		).toBe("/?skill=python");
	});

	it("renders a latest open jobs teaser that links to the jobs board", async () => {
		vi.mocked(loadInitialJobsChunk).mockResolvedValue(
			jobsChunk([
				latestJob({
					id: "job-1",
					title: "Staff Engineer",
					company: "Acme",
					source: "a16z",
				}),
				latestJob({
					id: "job-2",
					title: "Designer",
					company: "Beta",
					source: "yc",
				}),
			]),
		);
		renderDashboard(
			<ExplorerDashboard
				manifest={dashboardManifest()}
				lineage={null}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);
		expect(await screen.findByText("Staff Engineer")).not.toBeNull();
		expect(screen.getByText("Acme · a16z")).not.toBeNull();
		expect(screen.getByRole("link", { name: /Staff Engineer/i }).getAttribute("href")).toBe(
			"/?job=job-1",
		);
		expect(screen.getByRole("link", { name: "Open jobs board" }).getAttribute("href")).toBe(
			"/",
		);
		expect(screen.getByText(/7d sync/)).not.toBeNull();
		expect(screen.getByText(/12 new/)).not.toBeNull();
	});

	it("uses the empty-state shell when lineage is missing", () => {
		renderDashboard(
			<ExplorerDashboard
				manifest={dashboardManifest()}
				lineage={null}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);
		expect(screen.getByText("Lineage not in this snapshot")).not.toBeNull();
		expect(screen.getByText(/source → provider → board → job/)).not.toBeNull();
		expect(screen.getByText(/just web-search-index/)).not.toBeNull();
		const empty = screen.getByText("Lineage not in this snapshot").closest(".opps-empty");
		expect(empty).not.toBeNull();
	});

	it("renders quality coverage at the true percent, including sparse compensation", () => {
		const { container } = renderDashboard(
			<ExplorerDashboard
				manifest={dashboardManifest()}
				lineage={null}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);
		expect(screen.getByText(/5 \/ 100 \(5%\)/)).not.toBeNull();
		const fills = [...container.querySelectorAll('[aria-hidden="true"]')].map((node) =>
			node.getAttribute("style"),
		);
		expect(fills.some((style) => style?.includes("width: 5%"))).toBe(true);
		expect(fills.some((style) => style?.includes("width: 8%"))).toBe(false);
	});

	it("renders suggestion index as metric strips, not nested mini-cards", () => {
		renderDashboard(
			<ExplorerDashboard
				manifest={dashboardManifest()}
				lineage={null}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);
		expect(screen.getByText("Suggestion index")).not.toBeNull();
		expect(screen.getByRole("button", { name: "Inspect sources for a16z" })).not.toBeNull();
		expect(
			screen.getByRole("link", { name: "Open departments Engineering on jobs board" }),
		).not.toBeNull();
	});

	it("tightens hierarchy with snapshot, coverage, lineage, and inspect CTAs", async () => {
		const { container } = renderDashboard(
			<ExplorerDashboard
				manifest={dashboardManifest()}
				lineage={lineageAggregate}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);
		expect(await screen.findByText("Full lineage map", {}, { timeout: 5000 })).not.toBeNull();
		const kickers = [...container.querySelectorAll(".opps-kicker")].map(
			(node) => node.textContent,
		);
		expect(kickers).toEqual(
			expect.arrayContaining([
				"OpenOppsDB explorer",
				"Snapshot",
				"Coverage",
				"Lineage",
				"Index",
			]),
		);
		expect(screen.getAllByRole("button", { name: /Inspect rows/i }).length).toBeGreaterThan(1);
	});

	it("does not fetch the full jobs index when latest-jobs initialPath is absent", async () => {
		const manifest = dashboardManifest();
		delete manifest.entities.jobs.initialPath;
		renderDashboard(
			<ExplorerDashboard
				manifest={manifest}
				lineage={null}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);
		await waitFor(() => {
			expect(loadInitialJobsChunk).not.toHaveBeenCalled();
		});
		expect(screen.getByText("Latest open jobs are not in this snapshot yet.")).not.toBeNull();
	});
});

function renderDashboard(ui: ReactElement) {
	return render(ui, {
		wrapper: withNuqsTestingAdapter({ hasMemory: true }),
	});
}

function dashboardManifest(): SearchManifest {
	return {
		version: 6,
		snapshotAt: "2026-01-01T00:00:00Z",
		source: { database: "kaggle/openoppsdb.sqlite", tables: ["jobs"] },
		defaultEntity: "jobs",
		defaultFilters: { jobs: { status: "open" } },
		entities: {
			jobs: {
				columns: ["id"],
				count: 100,
				initialPath: "/data/openopps-search/jobs/latest.json",
			},
			boards: { columns: ["key"], count: 10 },
			providers: { columns: ["id"], count: 20 },
		},
		facets: {
			sources: ["a16z"],
			providerIds: ["greenhouse"],
			jobStatuses: ["open"],
			supportLevels: ["full"],
			routeStatuses: ["ok"],
			workplaces: ["remote"],
			employmentTypes: ["full-time"],
		},
		suggestions: {
			sources: [{ value: "a16z", label: "a16z", count: 40, normalized: "a16z" }],
			providers: [
				{ value: "greenhouse", label: "greenhouse", count: 50, normalized: "greenhouse" },
			],
			locations: [{ value: "Remote", label: "Remote", count: 20, normalized: "remote" }],
			departments: [
				{ value: "Engineering", label: "Engineering", count: 15, normalized: "engineering" },
			],
			companies: [{ value: "Acme", label: "Acme", count: 10, normalized: "acme" }],
			skills: [{ value: "python", label: "python", count: 8, normalized: "python" }],
			workplaces: [{ value: "remote", label: "remote", count: 12, normalized: "remote" }],
			employmentTypes: [
				{ value: "full-time", label: "full-time", count: 9, normalized: "full-time" },
			],
		},
		dashboard: {
			snapshotAt: "2026-01-01T00:00:00Z",
			totals: {
				sourceRows: 12,
				providerRoutes: 20,
				boards: 10,
				jobs: 100,
				openJobs: 80,
			},
			top: {
				sourcesByJobs: [{ value: "a16z", count: 40 }],
				providersByJobs: [{ value: "greenhouse", count: 50 }],
				locations: [{ value: "Remote", count: 20 }],
				departments: [{ value: "Engineering", count: 15 }],
				teams: [],
				companies: [{ value: "Acme", count: 10 }],
				skills: [{ value: "python", count: 8 }],
			},
			dataQuality: [
				{ key: "description", count: 90, total: 100, percentage: 90 },
				{ key: "compensation", count: 5, total: 100, percentage: 5 },
			],
			routeHealth: {
				supportLevels: [
					{ value: "full", count: 12 },
					{ value: "unsupported", count: 3 },
				],
				routeStatuses: [
					{ value: "ok", count: 14 },
					{ value: "error", count: 2 },
				],
			},
			artifacts: {
				jobChunks: 2,
				detailShardBuckets: 1024,
				detailShardRecords: 80,
			},
			sync: {
				windowDays: 7,
				windowStart: "2025-12-25T00:00:00Z",
				runCount: 4,
				totals7d: { new: 12, changed: 4, closed: 2, reopened: 1 },
				medianDaysOpenByProvider: [],
				topBoardsByChurn: [],
			},
		},
	};
}

function emptyJobsChunk(): SearchChunk {
	return { version: 6, entity: "jobs", columns: ["id"], count: 0, rows: [] };
}

function jobsChunk(rows: SearchRow[]): SearchChunk {
	return { version: 6, entity: "jobs", columns: ["id"], count: rows.length, rows };
}

function latestJob({
	id,
	title,
	company,
	source,
}: {
	id: string;
	title: string;
	company: string;
	source: string;
}): SearchRow {
	const row: SearchRow = [];
	row[0] = id;
	row[1] = source;
	row[4] = "open";
	row[5] = title;
	row[6] = company;
	row[18] = "2026-01-01T00:00:00Z";
	return row;
}

const lineageAggregate: LineageAggregate = {
	version: SEARCH_VERSION,
	snapshotAt: "2026-01-01T00:00:00Z",
	counts: {
		sourceRows: 2,
		sources: 2,
		providerRoutes: 3,
		providers: 2,
		boards: 2,
		jobs: 20,
		openJobs: 15,
	},
	nodes: {
		sources: [],
		providers: [],
		boards: [],
	},
	edges: {
		sourceProviders: [
			{ sourceKey: "a16z", providerId: "greenhouse", routes: 2, jobs: 15, openJobs: 12 },
		],
		sourceBoards: [
			{ sourceKey: "a16z", boardKey: "a16z:acme", boards: 1, jobs: 15, openJobs: 12 },
		],
		providerBoards: [
			{
				sourceKey: "a16z",
				providerId: "greenhouse",
				boardKey: "a16z:acme",
				routes: 2,
				jobs: 15,
				openJobs: 12,
			},
		],
	},
};
