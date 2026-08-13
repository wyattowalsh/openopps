import {
	getJobSitemapUrls,
	shouldNoIndexDeployment,
} from "@/lib/jobs-sitemap-data";

export const dynamic = "force-dynamic";

export async function GET(
	_request: Request,
	{ params }: { params: Promise<{ id: string }> },
) {
	if (shouldNoIndexDeployment()) {
		return new Response("Not found.\n", { status: 404 });
	}
	const id = parseSitemapId((await params).id);
	if (id === null) {
		return new Response("Not found.\n", { status: 404 });
	}
	const urls = await getJobSitemapUrls(id);
	if (urls.length === 0) {
		return new Response("Not found.\n", { status: 404 });
	}
	return new Response(renderSitemap(urls), {
		headers: {
			"Cache-Control": "public, max-age=0, must-revalidate",
			"Content-Type": "application/xml; charset=utf-8",
			"X-Content-Type-Options": "nosniff",
		},
	});
}

function parseSitemapId(value: string) {
	const match = /^(0|[1-9]\d{0,14})\.xml$/.exec(value);
	if (!match) {
		return null;
	}
	const id = Number(match[1]);
	return Number.isSafeInteger(id) ? id : null;
}

function renderSitemap(
	urls: Awaited<ReturnType<typeof getJobSitemapUrls>>,
) {
	const entries = urls.map((entry) => {
		const lastModified =
			entry.lastModified instanceof Date
				? entry.lastModified.toISOString()
				: entry.lastModified;
		return [
			"<url>",
			`<loc>${escapeXml(entry.url)}</loc>`,
			lastModified
				? `<lastmod>${escapeXml(String(lastModified))}</lastmod>`
				: "",
			entry.changeFrequency
				? `<changefreq>${escapeXml(entry.changeFrequency)}</changefreq>`
				: "",
			entry.priority === undefined
				? ""
				: `<priority>${entry.priority}</priority>`,
			"</url>",
		]
			.filter(Boolean)
			.join("\n");
	});
	return [
		'<?xml version="1.0" encoding="UTF-8"?>',
		'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
		...entries,
		"</urlset>",
		"",
	].join("\n");
}

function escapeXml(value: string) {
	return value.replace(
		/[&<>"']/g,
		(character) =>
			({
				"&": "&amp;",
				"<": "&lt;",
				">": "&gt;",
				'"': "&quot;",
				"'": "&apos;",
			})[character]!,
	);
}
