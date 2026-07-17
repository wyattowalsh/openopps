import { describe, expect, it } from "vitest";

import { getDocsOgPage } from "@/lib/docs-og-data";
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

	it("loads lightweight page metadata without compiled MDX imports", () => {
		expect(getDocsOgPage([])).toMatchObject({
			slug: [],
			title: "Start Here",
		});
		expect(getDocsOgPage(["providers"])).toMatchObject({
			slug: ["providers"],
			title: "Providers",
		});
	});
});
