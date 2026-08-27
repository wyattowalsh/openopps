import { buildLlmsSiteIndex } from "@/lib/llms-site-index";
import { canonicalSiteUrl } from "@/lib/site-metadata";
import { getPageMarkdownUrl, source } from "@/lib/source";

export const revalidate = false;

export function GET() {
	const docs = source.getPages().map((page) => ({
		title: page.data.title,
		url: canonicalSiteUrl(page.url),
		markdownUrl: canonicalSiteUrl(getPageMarkdownUrl(page).url),
		description: page.data.description,
	}));
	return new Response(buildLlmsSiteIndex(docs), {
		headers: {
			"Content-Type": "text/markdown; charset=utf-8",
		},
	});
}
