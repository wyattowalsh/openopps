import fs from "node:fs";
import path from "node:path";

export type DocsOgPage = {
	slug: string[];
	title: string;
	description?: string;
};

const DOCS_CONTENT_DIR = path.join(process.cwd(), "content", "docs");

let pagesCache: DocsOgPage[] | null = null;

export function getDocsOgPages() {
	if (!pagesCache) {
		pagesCache = fs
			.readdirSync(DOCS_CONTENT_DIR)
			.filter((file) => file.endsWith(".mdx"))
			.sort((left, right) => slugSortKey(left).localeCompare(slugSortKey(right)))
			.map(readDocsOgPage);
	}
	return pagesCache;
}

export function getDocsOgPage(slug: string[]) {
	return (
		getDocsOgPages().find(
			(page) => page.slug.length === slug.length && page.slug.every((part, index) => part === slug[index]),
		) ?? null
	);
}

export function clearDocsOgPagesCacheForTests() {
	pagesCache = null;
}

function readDocsOgPage(file: string): DocsOgPage {
	const frontmatter = parseFrontmatter(
		fs.readFileSync(path.join(DOCS_CONTENT_DIR, file), "utf8"),
	);
	return {
		slug: file === "index.mdx" ? [] : [file.replace(/\.mdx$/, "")],
		title: frontmatter.title ?? "OpenOpps Docs",
		description: frontmatter.description,
	};
}

function parseFrontmatter(markdown: string) {
	const match = /^---\r?\n([\s\S]*?)\r?\n---/.exec(markdown);
	const fields: Record<string, string> = {};
	if (!match) {
		return fields;
	}
	for (const line of match[1].split(/\r?\n/)) {
		const field = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
		if (!field) {
			continue;
		}
		fields[field[1]] = stripQuotes(field[2].trim());
	}
	return fields;
}

function stripQuotes(value: string) {
	if (
		(value.startsWith('"') && value.endsWith('"')) ||
		(value.startsWith("'") && value.endsWith("'"))
	) {
		return value.slice(1, -1);
	}
	return value;
}

function slugSortKey(file: string) {
	return file === "index.mdx" ? "" : file;
}
