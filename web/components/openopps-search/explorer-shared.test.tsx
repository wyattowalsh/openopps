// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
	CoverageMeter,
	ExplorerFilterSelect,
	ExplorerMetric,
	jobsBoardSearchHref,
	RankedLedgerList,
	clampCoveragePercent,
	coverageShare,
	formatLedgerRank,
	rankedTopValueItems,
	routeHealthTone,
} from "./explorer-shared";

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

const LONG_WORKPLACE = "On-site San Francisco Bay Area, California, USA";

describe("ExplorerFilterSelect", () => {
	it("constrains native selects so long option labels cannot size the control", () => {
		expect(LONG_WORKPLACE).toHaveLength(47);

		const { container } = render(
			<ExplorerFilterSelect
				label="Workplace"
				value=""
				onChange={vi.fn()}
				options={[
					{ value: "", label: "Any" },
					{ value: LONG_WORKPLACE, label: LONG_WORKPLACE },
				]}
			/>,
		);

		const select = screen.getByRole("combobox", { name: "Workplace" });
		expect(select.classList.contains("opps-select")).toBe(true);
		expect(select.classList.contains("w-full")).toBe(true);
		expect(select.classList.contains("min-w-0")).toBe(true);
		expect(select.classList.contains("max-w-full")).toBe(true);
		expect(select.classList.contains("overflow-hidden")).toBe(true);
		expect(select.classList.contains("text-ellipsis")).toBe(true);

		const label = container.querySelector("label");
		expect(label?.classList.contains("min-w-0")).toBe(true);
		expect(label?.classList.contains("max-w-full")).toBe(true);
	});
});

describe("ranked coverage helpers", () => {
	it("keeps coverage percents honest at 0 and 100 with no 8% floor", () => {
		expect(clampCoveragePercent(0)).toBe(0);
		expect(clampCoveragePercent(5.4)).toBe(5);
		expect(clampCoveragePercent(100)).toBe(100);
		expect(coverageShare(0, 100)).toBe(0);
		expect(coverageShare(80, 100)).toBe(80);
		expect(coverageShare(4, 80)).toBe(5);
	});

	it("formats ledger ranks and jobs-board deep links", () => {
		expect(formatLedgerRank(0)).toBe("01");
		expect(formatLedgerRank(7)).toBe("08");
		expect(jobsBoardSearchHref({ job: "job-1" })).toBe("/?job=job-1");
		expect(jobsBoardSearchHref({ department: "Engineering" })).toBe(
			"/?department=Engineering",
		);
		expect(jobsBoardSearchHref({ q: "Acme" })).toBe("/?q=Acme");
		expect(jobsBoardSearchHref({ skill: "python" })).toBe("/?skill=python");
		expect(jobsBoardSearchHref({})).toBe("/");
	});

	it("maps route-health values to labeled tones", () => {
		expect(routeHealthTone("full")).toBe("success");
		expect(routeHealthTone("detect")).toBe("warning");
		expect(routeHealthTone("unsupported")).toBe("error");
		expect(routeHealthTone("ok")).toBe("success");
		expect(routeHealthTone("error")).toBe("error");
		expect(routeHealthTone("unknown")).toBe("info");
	});

	it("ranks top values with share-of-max bars and snapshot share", () => {
		const items = rankedTopValueItems(
			[
				{ value: "a16z", count: 40 },
				{ value: "yc", count: 10 },
			],
			{ snapshotTotal: 100, inspectNoun: "jobs", onSelect: () => {} },
		);
		expect(items[0]?.barPercent).toBe(100);
		expect(items[0]?.snapshotPercent).toBe(40);
		expect(items[1]?.barPercent).toBe(25);
		expect(items[1]?.snapshotPercent).toBe(10);
		expect(items[0]?.activateLabel).toBe("Inspect jobs for a16z");
	});
});

describe("CoverageMeter", () => {
	it("renders a ruled radius-sm track at the true percent, including 0%", () => {
		const { container, rerender } = render(
			<CoverageMeter percent={0} label="0% open" tone="info" />,
		);
		const fill = container.querySelector('[aria-hidden="true"]');
		expect(fill).not.toBeNull();
		expect(fill?.getAttribute("style")).toContain("width: 0%");
		expect(fill?.parentElement?.className).toContain("rounded-[var(--opps-radius-sm)]");
		expect(fill?.parentElement?.className).not.toContain("rounded-full");
		expect(screen.getByText("0% open")).not.toBeNull();

		rerender(<CoverageMeter percent={5} label="5%" />);
		expect(container.querySelector('[aria-hidden="true"]')?.getAttribute("style")).toContain(
			"width: 5%",
		);
	});
});

describe("ExplorerMetric", () => {
	it("pairs the jobs count with an open-share bar and inspects on click", () => {
		const onActivate = vi.fn();
		const { container } = render(
			<ExplorerMetric
				label="jobs"
				value={100}
				sharePercent={80}
				shareLabel="80% open"
				onActivate={onActivate}
			/>,
		);
		expect(screen.getByText("100")).not.toBeNull();
		expect(screen.getByText("80% open")).not.toBeNull();
		const fill = container.querySelector('[aria-hidden="true"]');
		expect(fill?.getAttribute("style")).toContain("width: 80%");
		fireEvent.click(screen.getByRole("button", { name: "Inspect jobs" }));
		expect(onActivate).toHaveBeenCalledTimes(1);
	});
});

describe("RankedLedgerList", () => {
	it("renders mono ranks, tabular counts, and inspect buttons without pill tracks", () => {
		const onActivate = vi.fn();
		const { container } = render(
			<RankedLedgerList
				emptyLabel="none"
				items={[
					{
						key: "a16z",
						label: "a16z",
						count: 40,
						barPercent: 100,
						snapshotPercent: 40,
						onActivate,
						activateLabel: "Inspect jobs for a16z",
					},
					{
						key: "yc",
						label: "yc",
						count: 10,
						barPercent: 25,
						snapshotPercent: 10,
					},
				]}
			/>,
		);
		expect(screen.getByText("01")).not.toBeNull();
		expect(screen.getByText("02")).not.toBeNull();
		expect(screen.getByText("40")).not.toBeNull();
		expect(screen.getByText("40%")).not.toBeNull();
		expect(container.querySelector(".rounded-full")).toBeNull();
		expect(
			[...container.querySelectorAll("div")].some((node) =>
				node.className.includes("rounded-[var(--opps-radius-sm)]"),
			),
		).toBe(true);
		fireEvent.click(screen.getByRole("button", { name: "Inspect jobs for a16z" }));
		expect(onActivate).toHaveBeenCalledTimes(1);
	});

	it("deep-links href rows to the jobs board", () => {
		render(
			<RankedLedgerList
				emptyLabel="none"
				items={[
					{
						key: "python",
						label: "python",
						count: 8,
						barPercent: 100,
						href: jobsBoardSearchHref({ skill: "python" }),
						activateLabel: "Open python on jobs board",
					},
				]}
			/>,
		);
		expect(screen.getByRole("link", { name: "Open python on jobs board" }).getAttribute("href")).toBe(
			"/?skill=python",
		);
	});
});
