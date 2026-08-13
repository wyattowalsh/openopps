import type { MetadataRoute } from "next";

import { getJobSitemapCount, shouldNoIndexDeployment } from "@/lib/jobs-sitemap-data";
import { siteUrl } from "@/lib/shared";

export const dynamic = "force-dynamic";

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
			{
				userAgent: "*",
				allow: "/",
				disallow: ["/api/"],
			},
		],
		sitemap: sitemaps,
	};
}
