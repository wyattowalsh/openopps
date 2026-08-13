import { afterEach, describe, expect, it, vi } from "vitest";

import { clearStaticJobDataCachesForTests, getStaticJobDetailIds } from "@/lib/jobs-static-data";
import { siteUrl } from "@/lib/shared";

import { getPublicJobDetail } from "./jobs-public-data";
import {
	getAllowlistedPublicSearchOrigin,
	getConfiguredPublicDataChannel,
} from "./jobs-public-origin";

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

	it("honors OPENOPPS_PUBLIC_DATA_ORIGIN override in development", () => {
		vi.stubEnv("NODE_ENV", "development");
		process.env.OPENOPPS_PUBLIC_DATA_ORIGIN = "http://127.0.0.1:3000";
		expect(getAllowlistedPublicSearchOrigin().href).toBe("http://127.0.0.1:3000/");
	});

	it("rejects non-https origins in production without insecure override", () => {
		vi.stubEnv("NODE_ENV", "production");
		delete process.env.VERCEL_ENV;
		delete process.env.NEXT_PUBLIC_VERCEL_ENV;
		delete process.env.OPENOPPS_PUBLIC_DATA_ORIGIN_ALLOW_INSECURE;
		process.env.OPENOPPS_PUBLIC_DATA_ORIGIN = "http://127.0.0.1:3000";
		expect(() => getAllowlistedPublicSearchOrigin()).toThrow(/https/i);
	});

	it("allows siteUrl host over https in production", () => {
		vi.stubEnv("NODE_ENV", "production");
		delete process.env.VERCEL_ENV;
		delete process.env.NEXT_PUBLIC_VERCEL_ENV;
		delete process.env.OPENOPPS_PUBLIC_DATA_ORIGIN_ALLOW_INSECURE;
		process.env.OPENOPPS_PUBLIC_DATA_ORIGIN = siteUrl;
		expect(getAllowlistedPublicSearchOrigin().href).toBe(`${siteUrl}/`);
	});

	it("accepts only normalized safe public-data channel names", () => {
		process.env.OPENOPPS_PUBLIC_DATA_CHANNEL = "production";
		expect(getConfiguredPublicDataChannel()).toBe("production");
		process.env.OPENOPPS_PUBLIC_DATA_CHANNEL = "../preview";
		expect(() => getConfiguredPublicDataChannel()).toThrow(/channel/i);
	});
});
