import type { MetadataRoute } from "next";

import { getJobSitemapCount, shouldNoIndexDeployment } from "@/lib/jobs-sitemap-data";
import { siteUrl } from "@/lib/shared";

export const dynamic = "force-dynamic";

const PUBLIC_SEARCH_AND_TRAINING_BOTS = [
	"Googlebot",
	"OAI-SearchBot",
	"Claude-SearchBot",
	"PerplexityBot",
	"GPTBot",
	"ClaudeBot",
	"Google-Extended",
] as const;

function publicPageRules(userAgent: string) {
	return {
		userAgent,
		allow: "/",
		disallow: ["/api/"],
	};
}

export default async function robots(): Promise<MetadataRoute.Robots> {
	if (shouldNoIndexDeployment()) {
		return {
			rules: {
				userAgent: "*",
				disallow: "/",
			},
		};
	}
	const jobSitemapCount = await getJobSitemapCount();
	const sitemaps = [
		`${siteUrl}/sitemap.xml`,
		...Array.from({ length: jobSitemapCount }, (_, id) =>
			`${siteUrl}/jobs/sitemap/${id}.xml`,
		),
	];
	return {
		rules: [
			publicPageRules("*"),
			...PUBLIC_SEARCH_AND_TRAINING_BOTS.map((userAgent) =>
				publicPageRules(userAgent),
			),
		],
		sitemap: sitemaps,
		host: new URL(siteUrl).host,
	};
}
