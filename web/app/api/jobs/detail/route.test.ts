import { afterEach, describe, expect, it, vi } from "vitest";

const { getPublicJobDetail } = vi.hoisted(() => ({
	getPublicJobDetail: vi.fn(),
}));

vi.mock("@/lib/jobs-public-data", () => ({ getPublicJobDetail }));

import { GET } from "./route";

afterEach(() => {
	vi.clearAllMocks();
});

describe("job detail route", () => {
	it("loads detail through the unified public-data client without a request-origin override", async () => {
		getPublicJobDetail.mockResolvedValue({ id: "source:provider:job-a" });

		const response = await GET(
			new Request(
				"https://untrusted-request-host.example/api/jobs/detail?id=source%3Aprovider%3Ajob-a",
			),
		);

		expect(response.status).toBe(200);
		expect(getPublicJobDetail).toHaveBeenCalledWith("source:provider:job-a");
		expect(getPublicJobDetail).toHaveBeenCalledTimes(1);
	});

	it("rejects missing ids and maps missing details to 404", async () => {
		const missingId = await GET(
			new Request("https://openopps.example/api/jobs/detail"),
		);
		getPublicJobDetail.mockResolvedValue(null);
		const missingDetail = await GET(
			new Request("https://openopps.example/api/jobs/detail?id=missing"),
		);

		expect(missingId.status).toBe(400);
		expect(missingDetail.status).toBe(404);
	});
});
