import { describe, expect, it } from "vitest";

import { buildLlmsSiteIndex } from "@/lib/llms-site-index";
import { siteUrl } from "@/lib/shared";

describe("llms-site-index", () => {
	it("emits an llmstxt.org v2 site index with jobs, explorer, docs, and markdown", () => {
		const text = buildLlmsSiteIndex([
			{
				title: "CLI",
				url: `${siteUrl}/docs/cli`,
				markdownUrl: `${siteUrl}/llms.mdx/docs/cli/content.md`,
				description: "Command groups",
			},
		]);
		expect(text.startsWith("# OpenOpps\n")).toBe(true);
		expect(text).toContain(`> OpenOpps is a public hiring snapshot`);
		expect(text).toContain("## Product");
		expect(text).toContain("## Docs");
		expect(text).toContain("## Markdown");
		expect(text).toContain(`[Jobs board](${siteUrl})`);
		expect(text).toContain(`[Explorer](${siteUrl}/explorer)`);
		expect(text).toContain(`[Latest open jobs feed](${siteUrl}/feed.xml)`);
		expect(text).toContain(`[CLI](${siteUrl}/docs/cli)`);
		expect(text).toContain(
			`[CLI (markdown)](${siteUrl}/llms.mdx/docs/cli/content.md)`,
		);
		expect(text).toContain(`/llms-full.txt`);
		expect(text).not.toContain("/api/jobs/search");
	});
});
