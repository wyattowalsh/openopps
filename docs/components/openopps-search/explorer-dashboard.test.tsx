// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ExplorerDashboard } from "./explorer-dashboard";
import type { LineageAggregate } from "./search-types";
import { SEARCH_VERSION } from "./search-utils";

afterEach(() => {
	cleanup();
});

describe("ExplorerDashboard", () => {
	it("renders full source-provider-board-job lineage analysis", () => {
		render(
			<ExplorerDashboard
				manifest={null}
				lineage={lineageAggregate}
				loading={false}
				onInspectRows={() => {}}
			/>,
		);

		expect(screen.getByText("Full lineage map")).not.toBeNull();
		expect(screen.getByText("Source-provider routes")).not.toBeNull();
		expect(screen.getByText("Source-board reach")).not.toBeNull();
		expect(screen.getByText("Board job paths")).not.toBeNull();
		expect(screen.getByText("a16z -> greenhouse -> a16z:acme")).not.toBeNull();
		expect(screen.getByText("12 / 15 open")).not.toBeNull();
	});
});

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
