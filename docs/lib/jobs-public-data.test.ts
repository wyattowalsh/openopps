import { afterEach, describe, expect, it, vi } from "vitest";

import { clearStaticJobDataCachesForTests, getStaticJobDetailIds } from "@/lib/jobs-static-data";
import { siteUrl } from "@/lib/shared";

import {
	getAllowlistedPublicSearchOrigin,
	getPublicJobDetail,
} from "./jobs-public-data";

describe("jobs public data", () => {
	const originalEnv = { ...process.env };

	afterEach(() => {
		process.env = { ...originalEnv };
		vi.restoreAllMocks();
		clearStaticJobDataCachesForTests();
	});

	it("loads job detail from committed filesystem shards without HTTP", async () => {
		const fetchMock = vi.fn();
		vi.stubGlobal("fetch", fetchMock);

		const ids = getStaticJobDetailIds();
		const detail = await getPublicJobDetail(ids[0]);

		expect(detail?.id).toBe(ids[0]);
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it("returns null for invalid job id encoding", async () => {
		await expect(getPublicJobDetail("%E0%A4%A")).resolves.toBeNull();
	});

	it("uses allowlisted site origin for search artifact fetches", () => {
		delete process.env.OPENOPPS_PUBLIC_DATA_ORIGIN;
		expect(getAllowlistedPublicSearchOrigin().href).toBe(`${siteUrl}/`);
	});

	it("honors OPENOPPS_PUBLIC_DATA_ORIGIN override", () => {
		process.env.OPENOPPS_PUBLIC_DATA_ORIGIN = "http://127.0.0.1:3000";
		expect(getAllowlistedPublicSearchOrigin().href).toBe("http://127.0.0.1:3000/");
	});
});