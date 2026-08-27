import { beforeEach, describe, expect, it, vi } from "vitest";

import { GET, dynamic } from "@/app/feed.xml/route";

vi.mock("@/lib/job-detail-utils", () => ({
	shouldNoIndexDeployment: vi.fn(),
}));

vi.mock("@/lib/jobs-feed-data", () => ({
	getLatestOpenJobsAtomFeed: vi.fn(),
}));

import { shouldNoIndexDeployment } from "@/lib/job-detail-utils";
import { getLatestOpenJobsAtomFeed } from "@/lib/jobs-feed-data";

const shouldNoIndexDeploymentMock = vi.mocked(shouldNoIndexDeployment);
const getLatestOpenJobsAtomFeedMock = vi.mocked(getLatestOpenJobsAtomFeed);

describe("feed.xml route", () => {
	beforeEach(() => {
		shouldNoIndexDeploymentMock.mockReset();
		getLatestOpenJobsAtomFeedMock.mockReset();
	});	it("is request-rendered like other snapshot metadata routes", () => {
		expect(dynamic).toBe("force-dynamic");
	});

	it("fails closed on noindex deployments", async () => {
		shouldNoIndexDeploymentMock.mockReturnValue(true);
		expect((await GET()).status).toBe(404);
		expect(getLatestOpenJobsAtomFeedMock).not.toHaveBeenCalled();
	});

	it("serves Atom XML from the snapshot feed helper", async () => {
		shouldNoIndexDeploymentMock.mockReturnValue(false);
		getLatestOpenJobsAtomFeedMock.mockResolvedValue({
			body: '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>\n',
			updated: "2026-08-26T00:00:00.000000Z",
		});
		const response = await GET();
		expect(response.status).toBe(200);
		expect(response.headers.get("content-type")).toBe(
			"application/atom+xml; charset=utf-8",
		);
		expect(await response.text()).toContain("http://www.w3.org/2005/Atom");
	});
});
