import { canonicalSiteUrl, jobsFeedUrl, siteWideCopy } from "@/lib/site-metadata";

export type LlmsDocsEntry = {
	title: string;
	url: string;
	markdownUrl: string;
	description?: string;
};

function bullet(title: string, url: string, note?: string) {
	const suffix = note?.trim() ? `: ${note.trim()}` : "";
	return `- [${title}](${url})${suffix}`;
}

export function buildLlmsSiteIndex(docs: LlmsDocsEntry[]) {
	const jobs = canonicalSiteUrl("/");
	const explorer = canonicalSiteUrl("/explorer");
	const docsIndex = canonicalSiteUrl("/docs");
	const llmsFull = canonicalSiteUrl("/llms-full.txt");
	const feed = jobsFeedUrl();
	const sortedDocs = [...docs].sort((left, right) => left.url.localeCompare(right.url));
	const lines = [
		"# OpenOpps",
		"",
		`> ${siteWideCopy.description}`,
		"",
		"This file is an llmstxt.org v2 index for agents. Prefer these links over scraping the HTML chrome. Public job search uses `/?q=` on the jobs board; do not call `/api/`.",
		"",
		"## Product",
		"",
		bullet("Jobs board", jobs, "Latest open jobs across sources and providers"),
		bullet("Explorer", explorer, "Snapshot coverage, quality, and row inspection"),
		bullet("Latest open jobs feed", feed, "Atom feed of indexable open jobs"),
		"",
		"## Docs",
		"",
		bullet("Docs index", docsIndex, "CLI, configuration, providers, and operations"),
		...sortedDocs.map((page) => bullet(page.title, page.url, page.description)),
		"",
		"## Markdown",
		"",
		bullet("Full docs dump", llmsFull, "Concatenated documentation markdown"),
		...sortedDocs.map((page) =>
			bullet(`${page.title} (markdown)`, page.markdownUrl),
		),
		"",
	];
	return `${lines.join("\n")}\n`;
}
