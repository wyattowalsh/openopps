import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { countSavedSearchMatches, summarizePublicJobsIndex, searchPublicJobsIndex } = vi.hoisted(() => ({
	countSavedSearchMatches: vi.fn(),
	summarizePublicJobsIndex: vi.fn(),
	searchPublicJobsIndex: vi.fn(),
}));

vi.mock("@/lib/jobs-search-service", async (importOriginal) => {
	const actual = await importOriginal<typeof import("@/lib/jobs-search-service")>();
	return {
		...actual,
		countSavedSearchMatches,
		summarizePublicJobsIndex,
		searchPublicJobsIndex,
	};
});

import { MAX_SAVED_SEARCH_COUNT_BODY_BYTES } from "./saved-search-limits";
import { GET, POST } from "./route";

afterEach(() => {
	vi.clearAllMocks();
	vi.unstubAllEnvs();
	vi.unstubAllGlobals();
});

beforeEach(() => {
	summarizePublicJobsIndex.mockResolvedValue({
		version: 6,
		entity: "jobs",
		snapshotAt: "2026-01-01T00:00:00Z",
		totalMatches: 1,
		sortKey: "latest",
		filtersHash: "{}",
	});
	countSavedSearchMatches.mockResolvedValue({
		version: 6,
		entity: "jobs",
		snapshotAt: "2026-01-01T00:00:00Z",
		semantics: "first-seen-v1",
		counts: [{ id: "search-a", totalMatches: 2, newMatches: 1 }],
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
	it("returns a bounded counts-only summary when summary=1", async () => {
		const response = await GET(
			new Request("http://127.0.0.1:3000/api/jobs/search?summary=1&sort=latest"),
		);

		expect(response.status).toBe(200);
		expect(summarizePublicJobsIndex).toHaveBeenCalledTimes(1);
		expect(summarizePublicJobsIndex).toHaveBeenCalledWith(
			expect.objectContaining({
				sortKey: "latest",
			}),
		);
		expect(searchPublicJobsIndex).not.toHaveBeenCalled();
		const body = await response.text();
		expect(JSON.parse(body)).toMatchObject({ totalMatches: 1 });
		expect(body).not.toContain("fingerprint");
	});

	it("accepts summary=true without enabling membership output", async () => {
		const response = await GET(
			new Request("http://127.0.0.1:3000/api/jobs/search?summary=true"),
		);

		expect(response.status).toBe(200);
		expect(summarizePublicJobsIndex).toHaveBeenCalledTimes(1);
		expect(searchPublicJobsIndex).not.toHaveBeenCalled();
	});

	it("counts a validated saved-search batch with private no-store caching", async () => {
		const response = await POST(
			new Request("http://127.0.0.1:3000/api/jobs/search", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					searches: [
						{
							id: "search-a",
							filters: { query: "platform" },
							sortKey: "latest",
							reviewedAt: "2026-01-01T00:00:00Z",
						},
					],
				}),
			}),
		);

		expect(response.status).toBe(200);
		expect(response.headers.get("Cache-Control")).toBe("private, no-store");
		expect(countSavedSearchMatches).toHaveBeenCalledWith(
			expect.objectContaining({
				searches: [
					expect.objectContaining({
						id: "search-a",
						reviewedAt: "2026-01-01T00:00:00Z",
					}),
				],
			}),
		);
		expect((await response.text()).length).toBeLessThan(MAX_SAVED_SEARCH_COUNT_BODY_BYTES);
	});

	it("rejects oversized and over-cardinality saved-search batches", async () => {
		const tooMany = await POST(
			new Request("http://127.0.0.1:3000/api/jobs/search", {
				method: "POST",
				body: JSON.stringify({
					searches: Array.from({ length: 26 }, (_, index) => ({
						id: `search-${index}`,
						filters: {},
						sortKey: "latest",
						reviewedAt: "2026-01-01T00:00:00Z",
					})),
				}),
			}),
		);
		const oversized = await POST(
			new Request("http://127.0.0.1:3000/api/jobs/search", {
				method: "POST",
				body: "x".repeat(MAX_SAVED_SEARCH_COUNT_BODY_BYTES + 1),
			}),
		);

		expect(tooMany.status).toBe(422);
		expect(oversized.status).toBe(413);
		expect(countSavedSearchMatches).not.toHaveBeenCalled();
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
