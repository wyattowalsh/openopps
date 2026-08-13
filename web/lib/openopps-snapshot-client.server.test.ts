import { afterEach, describe, expect, it, vi } from "vitest";

import {
	EXPECTED_BOARD_COLUMNS,
	EXPECTED_JOB_COLUMNS,
	EXPECTED_PROVIDER_COLUMNS,
} from "@/components/openopps-search/search-utils";

import { createPublicDataSnapshotClient } from "./openopps-snapshot-client.server";

const originalEnv = { ...process.env };

afterEach(() => {
	process.env = { ...originalEnv };
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe("server snapshot-client precedence", () => {
	it("uses the local v6 filesystem only when no remote origin or channel is configured", async () => {
		delete process.env.OPENOPPS_PUBLIC_DATA_ORIGIN;
		delete process.env.OPENOPPS_PUBLIC_DATA_CHANNEL;
		delete process.env.VERCEL;
		const fetchMock = vi.fn();
		vi.stubGlobal("fetch", fetchMock);

		const manifest = await createPublicDataSnapshotClient().getSearchManifest();

		expect(manifest.version).toBe(6);
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it("uses remote v6 HTTP without falling back to local files when an origin is configured", async () => {
		vi.stubEnv("NODE_ENV", "development");
		process.env.OPENOPPS_PUBLIC_DATA_ORIGIN = "https://data.openopps.test";
		delete process.env.OPENOPPS_PUBLIC_DATA_CHANNEL;
		const fetchMock = vi.fn(async () =>
			new Response(JSON.stringify(searchManifest), {
				headers: { "Content-Type": "application/json" },
			}),
		);
		vi.stubGlobal("fetch", fetchMock);

		await expect(
			createPublicDataSnapshotClient().getSearchManifest(),
		).resolves.toEqual(searchManifest);
		expect(fetchMock).toHaveBeenCalledWith(
			new URL("https://data.openopps.test/data/openopps-search/manifest.json"),
			expect.objectContaining({ cache: "no-store" }),
		);
	});

	it("uses deployed v6 HTTP when Vercel omits static assets from serverless traces", async () => {
		delete process.env.OPENOPPS_PUBLIC_DATA_ORIGIN;
		delete process.env.OPENOPPS_PUBLIC_DATA_CHANNEL;
		process.env.VERCEL = "1";
		const fetchMock = vi.fn(async () =>
			new Response(JSON.stringify(searchManifest), {
				headers: { "Content-Type": "application/json" },
			}),
		);
		vi.stubGlobal("fetch", fetchMock);

		await expect(
			createPublicDataSnapshotClient().getSearchManifest(),
		).resolves.toEqual(searchManifest);
		expect(fetchMock).toHaveBeenCalledWith(
			new URL("https://openopps.dev/data/openopps-search/manifest.json"),
			expect.objectContaining({ cache: "no-store" }),
		);
	});
});

const searchManifest = {
	version: 6,
	snapshotAt: "2026-08-12T12:00:00.000000Z",
	source: { database: "kaggle/openoppsdb.sqlite", tables: [] },
	defaultEntity: "jobs",
	defaultFilters: { jobs: { status: "open" } },
	entities: {
		jobs: { columns: EXPECTED_JOB_COLUMNS, count: 0 },
		boards: { columns: EXPECTED_BOARD_COLUMNS, count: 0 },
		providers: { columns: EXPECTED_PROVIDER_COLUMNS, count: 0 },
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
};
