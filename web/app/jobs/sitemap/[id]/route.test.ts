// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
	getJobSitemapUrls,
	shouldNoIndexDeployment,
} from "@/lib/jobs-sitemap-data";

import { GET } from "./route";

vi.mock("@/lib/jobs-sitemap-data", () => ({
	getJobSitemapUrls: vi.fn(),
	shouldNoIndexDeployment: vi.fn(),
}));

const getJobSitemapUrlsMock = vi.mocked(getJobSitemapUrls);
const shouldNoIndexDeploymentMock = vi.mocked(shouldNoIndexDeployment);

describe("job sitemap route", () => {
	beforeEach(() => {
		getJobSitemapUrlsMock.mockReset();
		shouldNoIndexDeploymentMock.mockReset();
		shouldNoIndexDeploymentMock.mockReturnValue(false);
	});

	it("renders escaped, well-formed XML from one canonical page", async () => {
		getJobSitemapUrlsMock.mockResolvedValue([
			{
				url: "https://openopps.dev/jobs/a?x=1&label=<platform>",
				lastModified: new Date("2026-02-03T04:05:06.123Z"),
				changeFrequency: "daily",
				priority: 0.5,
			},
		]);

		const response = await routeFor("0.xml");

		expect(response.status).toBe(200);
		expect(response.headers.get("content-type")).toBe(
			"application/xml; charset=utf-8",
		);
		expect(response.headers.get("cache-control")).toBe(
			"public, max-age=0, must-revalidate",
		);
		expect(response.headers.get("x-content-type-options")).toBe("nosniff");
		const xml = await response.text();
		expect(xml).toContain("x=1&amp;label=&lt;platform&gt;");
		const parsed = new DOMParser().parseFromString(xml, "application/xml");
		expect(parsed.querySelector("parsererror")).toBeNull();
		expect(parsed.querySelector("loc")?.textContent).toBe(
			"https://openopps.dev/jobs/a?x=1&label=<platform>",
		);
		expect(getJobSitemapUrlsMock).toHaveBeenCalledOnce();
		expect(getJobSitemapUrlsMock).toHaveBeenCalledWith(0);
	});

	it("fails closed before parsing or data access on a noindex deployment", async () => {
		shouldNoIndexDeploymentMock.mockReturnValue(true);

		expect((await routeFor("0.xml")).status).toBe(404);
		expect(getJobSitemapUrlsMock).not.toHaveBeenCalled();
	});

	it.each([
		"",
		"0",
		"-1.xml",
		"+1.xml",
		"01.xml",
		"1.0.xml",
		"9007199254740992.xml",
		"../1.xml",
	])("rejects non-canonical page id %j", async (id) => {
		expect((await routeFor(id)).status).toBe(404);
		expect(getJobSitemapUrlsMock).not.toHaveBeenCalled();
	});

	it("returns 404 for an out-of-range page", async () => {
		getJobSitemapUrlsMock.mockResolvedValue([]);

		expect((await routeFor("7.xml")).status).toBe(404);
		expect(getJobSitemapUrlsMock).toHaveBeenCalledOnce();
		expect(getJobSitemapUrlsMock).toHaveBeenCalledWith(7);
	});
});

function routeFor(id: string) {
	return GET(new Request(`https://openopps.dev/jobs/sitemap/${id}`), {
		params: Promise.resolve({ id }),
	});
}
