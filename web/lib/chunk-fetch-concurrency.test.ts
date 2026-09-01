import { describe, expect, it } from "vitest";

import { resolveChunkFetchConcurrency } from "./chunk-fetch-concurrency";

describe("resolveChunkFetchConcurrency", () => {
	it("clamps the in-worker fetch pool between 2 and 8 from hardwareConcurrency", () => {
		expect(resolveChunkFetchConcurrency({ hardwareConcurrency: 1 })).toBe(2);
		expect(resolveChunkFetchConcurrency({ hardwareConcurrency: 4 })).toBe(4);
		expect(resolveChunkFetchConcurrency({ hardwareConcurrency: 12 })).toBe(8);
	});

	it("uses a 2-8 default when hardwareConcurrency is missing", () => {
		expect(resolveChunkFetchConcurrency({})).toBe(4);
	});

	it("drops to one fetch on saveData or 2g links", () => {
		expect(
			resolveChunkFetchConcurrency({
				hardwareConcurrency: 8,
				saveData: true,
			}),
		).toBe(1);
		expect(
			resolveChunkFetchConcurrency({
				hardwareConcurrency: 8,
				effectiveType: "2g",
			}),
		).toBe(1);
		expect(
			resolveChunkFetchConcurrency({
				hardwareConcurrency: 8,
				effectiveType: "slow-2g",
			}),
		).toBe(1);
	});

	it("does not treat 3g or 4g as a save-data clamp", () => {
		expect(
			resolveChunkFetchConcurrency({
				hardwareConcurrency: 6,
				effectiveType: "4g",
			}),
		).toBe(6);
	});
});
