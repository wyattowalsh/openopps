import { describe, expect, it } from "vitest";

import { parseSnapshotChrome, searchManifestFromChrome } from "@/lib/snapshot-chrome";

const chromeFixture = {
	version: 6,
	snapshotAt: "2026-08-26T21:52:25.592259Z",
	openJobCount: 11160,
	kaggleDatasetId: "wyattowalsh/openoppsdb",
	source: { database: "kaggle/openoppsdb.sqlite" },
	counts: {
		snapshot: {
			database: "kaggle/openoppsdb.sqlite",
			sourceRows: 2871,
			providerRoutes: 1321,
			boards: 25907,
			jobs: 19310,
			openJobs: 11160,
		},
	},
	entities: {
		jobs: {
			initialPath: "/data/openopps-search/jobs/latest.json",
			file: "jobs/latest.json",
			count: 19310,
			chunkSize: 1000,
			chunkCount: 20,
		},
		boards: { count: 25907 },
		providers: { count: 1321 },
	},
	facetSourceCount: 1787,
};

describe("snapshot-chrome", () => {
	it("parses version 6 chrome and never accepts payload 7", () => {
		const chrome = parseSnapshotChrome(chromeFixture);
		expect(chrome.version).toBe(6);
		expect(chrome.openJobCount).toBe(11160);
		expect(chrome.snapshotAt).toContain("2026-08-26");
		expect(() => parseSnapshotChrome({ ...chromeFixture, version: 7 })).toThrow(
			/version 7/,
		);
	});

	it("projects chrome into metrics without pulling the typeahead manifest", () => {
		const manifest = searchManifestFromChrome(parseSnapshotChrome(chromeFixture));
		expect(manifest.entities.jobs.count).toBe(19310);
		expect(manifest.openJobCount).toBe(11160);
		expect(manifest.counts?.snapshot?.providerRoutes).toBe(1321);
	});
});
