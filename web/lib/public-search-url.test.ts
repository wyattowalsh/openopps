import { describe, expect, it } from "vitest";

import { resolvePublicSearchUrl } from "./public-search-url";

const base = new URL("https://openopps.dev/");

describe("resolvePublicSearchUrl", () => {
	it("resolves relative paths under /data/openopps-search/", () => {
		const url = resolvePublicSearchUrl(base, "/data/openopps-search/manifest.json");
		expect(url.href).toBe("https://openopps.dev/data/openopps-search/manifest.json");
		expect(url.origin).toBe(base.origin);
	});

	it("rejects empty paths", () => {
		expect(() => resolvePublicSearchUrl(base, "  ")).toThrow(/empty/i);
	});

	it("rejects absolute http(s) URLs", () => {
		expect(() =>
			resolvePublicSearchUrl(base, "https://evil.example/data/openopps-search/x"),
		).toThrow(/scheme/i);
	});

	it("rejects scheme-relative URLs", () => {
		expect(() => resolvePublicSearchUrl(base, "//evil.example/x")).toThrow(
			/scheme-relative/i,
		);
	});

	it("rejects backslashes", () => {
		expect(() =>
			resolvePublicSearchUrl(base, "/data/openopps-search\\manifest.json"),
		).toThrow(/backslash/i);
	});

	it("rejects .. segments", () => {
		expect(() =>
			resolvePublicSearchUrl(base, "/data/openopps-search/../secret"),
		).toThrow(/\.\./);
	});

	it("rejects . segments", () => {
		expect(() =>
			resolvePublicSearchUrl(base, "/data/openopps-search/./manifest.json"),
		).toThrow(/\./);
	});

	it("rejects paths outside /data/openopps-search/", () => {
		expect(() => resolvePublicSearchUrl(base, "/api/secret")).toThrow(
			/openopps-search/i,
		);
	});

	it("rejects encoded traversal attempts that become .. segments after split", () => {
		// Path is validated as literal segments before URL resolution for .. and .
		expect(() =>
			resolvePublicSearchUrl(base, "/data/openopps-search/foo/../bar"),
		).toThrow(/\.\./);
	});

	it("keeps same origin for nested shard paths", () => {
		const url = resolvePublicSearchUrl(
			base,
			"/data/openopps-search/jobs/chunks/chunk-0.json",
		);
		expect(url.pathname).toBe("/data/openopps-search/jobs/chunks/chunk-0.json");
		expect(url.origin).toBe(base.origin);
	});
});
