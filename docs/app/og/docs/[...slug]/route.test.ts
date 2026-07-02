import { describe, expect, it } from "vitest";

import { docsOgPageSlug } from "./route-utils";

describe("docs OG route slug parsing", () => {
	it("accepts generated image routes", () => {
		expect(docsOgPageSlug(["providers", "image.png"])).toEqual(["providers"]);
		expect(docsOgPageSlug(["image.png"])).toEqual([]);
	});

	it("rejects malformed routes without the image suffix", () => {
		expect(docsOgPageSlug(["providers"])).toBeNull();
		expect(docsOgPageSlug([])).toBeNull();
	});
});
