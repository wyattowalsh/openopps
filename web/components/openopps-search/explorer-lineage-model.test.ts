import { describe, expect, it } from "vitest";

import {
	buildLineageNetworkModel,
	lineageOpenJobShare,
} from "./explorer-lineage-model";
import type { LineageAggregate } from "./search-types";
import { SEARCH_VERSION } from "./search-utils";

describe("explorer lineage model", () => {
	it("builds a full source-provider-board-job lineage model", () => {
		const model = buildLineageNetworkModel(lineageAggregate, 2);

		expect(model.stages).toEqual([
			expect.objectContaining({
				key: "sources",
				value: 3,
				secondaryValue: 2,
				edgeCount: 2,
			}),
			expect.objectContaining({
				key: "providers",
				value: 4,
				secondaryValue: 2,
				edgeCount: 3,
			}),
			expect.objectContaining({
				key: "boards",
				value: 5,
				secondaryValue: 2,
			}),
			expect.objectContaining({
				key: "jobs",
				value: 30,
				secondaryValue: 21,
			}),
		]);
		expect(model.pathRows).toEqual([
			expect.objectContaining({
				sourceKey: "a16z",
				providerId: "greenhouse",
				boardKey: "a16z:acme",
				jobs: 12,
				openShare: 75,
			}),
			expect.objectContaining({
				sourceKey: "yc",
				providerId: "lever",
				boardKey: "yc:beta",
				jobs: 10,
				openShare: 50,
			}),
		]);
		expect(model.sourceProviderRows.map((row) => row.key)).toEqual([
			"a16z:greenhouse",
			"yc:lever",
		]);
		expect(model.sourceBoardRows.map((row) => row.key)).toEqual([
			"a16z:a16z:acme",
			"yc:yc:beta",
		]);
		expect(model.maxPathJobs).toBe(12);
		expect(model.maxSourceProviderJobs).toBe(12);
		expect(model.maxSourceBoardJobs).toBe(12);
	});

	it("derives missing path source keys from board keys", () => {
		const model = buildLineageNetworkModel(
			{
				...lineageAggregate,
				edges: {
					...lineageAggregate.edges,
					providerBoards: [
						{
							providerId: "ashbyhq",
							boardKey: "manual:gamma",
							jobs: 3,
							openJobs: 1,
						},
					],
				},
			},
			1,
		);

		expect(model.pathRows[0]).toMatchObject({
			sourceKey: "manual",
			providerId: "ashbyhq",
			boardKey: "manual:gamma",
			openShare: 33,
		});
	});

	it("keeps zero-job share bounded", () => {
		expect(lineageOpenJobShare(0, 0)).toBe(0);
	});
});

const lineageAggregate: LineageAggregate = {
	version: SEARCH_VERSION,
	snapshotAt: "2026-01-01T00:00:00Z",
	counts: {
		sourceRows: 3,
		sources: 2,
		providerRoutes: 4,
		providers: 2,
		boards: 5,
		jobs: 30,
		openJobs: 21,
	},
	nodes: {
		sources: [],
		providers: [],
		boards: [],
	},
	edges: {
		sourceProviders: [
			{ sourceKey: "a16z", providerId: "greenhouse", routes: 2, jobs: 12, openJobs: 9 },
			{ sourceKey: "yc", providerId: "lever", routes: 1, jobs: 10, openJobs: 5 },
		],
		sourceBoards: [
			{ sourceKey: "a16z", boardKey: "a16z:acme", boards: 1, jobs: 12, openJobs: 9 },
			{ sourceKey: "yc", boardKey: "yc:beta", boards: 1, jobs: 10, openJobs: 5 },
		],
		providerBoards: [
			{
				sourceKey: "yc",
				providerId: "lever",
				boardKey: "yc:beta",
				routes: 1,
				jobs: 10,
				openJobs: 5,
			},
			{
				sourceKey: "a16z",
				providerId: "greenhouse",
				boardKey: "a16z:acme",
				routes: 2,
				jobs: 12,
				openJobs: 9,
			},
			{
				sourceKey: "a16z",
				providerId: "ashbyhq",
				boardKey: "a16z:gamma",
				routes: 1,
				jobs: 8,
				openJobs: 7,
			},
		],
	},
};
