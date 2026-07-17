import { describe, expect, it } from "vitest";

import { docsMarkdownPageSlug } from "./route-utils";

describe("docsMarkdownPageSlug", () => {
	it("accepts generated content.md markdown URLs", () => {
		expect(docsMarkdownPageSlug(["content.md"])).toEqual([]);
		expect(docsMarkdownPageSlug(["providers", "content.md"])).toEqual([
			"providers",
		]);
	});

	it("rejects missing or malformed suffixes", () => {
		expect(docsMarkdownPageSlug(undefined)).toBeNull();
		expect(docsMarkdownPageSlug([])).toBeNull();
		expect(docsMarkdownPageSlug(["providers"])).toBeNull();
		expect(docsMarkdownPageSlug(["providers", "bad.md"])).toBeNull();
	});
});
