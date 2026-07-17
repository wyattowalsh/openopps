import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { summarizePublicJobsIndex, searchPublicJobsIndex } = vi.hoisted(() => ({
	summarizePublicJobsIndex: vi.fn(),
	searchPublicJobsIndex: vi.fn(),
}));

vi.mock("@/lib/jobs-search-service", async (importOriginal) => {
	const actual = await importOriginal<typeof import("@/lib/jobs-search-service")>();
	return {
		...actual,
		summarizePublicJobsIndex,
		searchPublicJobsIndex,
	};
});

import { GET } from "./route";

afterEach(() => {
	vi.clearAllMocks();
	vi.unstubAllEnvs();
	vi.unstubAllGlobals();
});

beforeEach(() => {
	summarizePublicJobsIndex.mockResolvedValue({
		version: 6,
		entity: "jobs",
		totalMatches: 1,
		sortKey: "latest",
		filtersHash: "{}",
		entries: [{ id: "job-a", fingerprint: "fp-a" }],
	});
	searchPublicJobsIndex.mockResolvedValue({
		version: 6,
		entity: "jobs",
		columns: [],
		count: 0,
		rows: [],
		totalMatches: 0,
		limit: 50,
		page: 1,
		pageSize: 50,
		totalPages: 1,
		hasNextPage: false,
		hasPreviousPage: false,
		truncated: false,
	});
});

describe("jobs search route", () => {
	it("requests fingerprints when summary=1", async () => {
		const response = await GET(
			new Request("http://127.0.0.1:3000/api/jobs/search?summary=1&sort=latest"),
		);

		expect(response.status).toBe(200);
		expect(summarizePublicJobsIndex).toHaveBeenCalledTimes(1);
		expect(summarizePublicJobsIndex).toHaveBeenCalledWith(
			expect.objectContaining({
				includeFingerprints: true,
				sortKey: "latest",
			}),
		);
		expect(searchPublicJobsIndex).not.toHaveBeenCalled();
		await expect(response.json()).resolves.toMatchObject({
			totalMatches: 1,
			entries: [{ id: "job-a", fingerprint: "fp-a" }],
		});
	});

	it("requests fingerprints when summary=true", async () => {
		const response = await GET(
			new Request("http://127.0.0.1:3000/api/jobs/search?summary=true"),
		);

		expect(response.status).toBe(200);
		expect(summarizePublicJobsIndex).toHaveBeenCalledWith(
			expect.objectContaining({ includeFingerprints: true }),
		);
		expect(searchPublicJobsIndex).not.toHaveBeenCalled();
	});

	it("uses searchPublicJobsIndex when summary is absent", async () => {
		const response = await GET(
			new Request("http://127.0.0.1:3000/api/jobs/search?q=platform&page=1"),
		);

		expect(response.status).toBe(200);
		expect(searchPublicJobsIndex).toHaveBeenCalledTimes(1);
		expect(summarizePublicJobsIndex).not.toHaveBeenCalled();
	});
});
