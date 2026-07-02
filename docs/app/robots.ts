import type { MetadataRoute } from "next";

import { getJobSitemapCount, shouldNoIndexDeployment } from "@/lib/jobs-static-data";
import { siteUrl } from "@/lib/shared";

export default function robots(): MetadataRoute.Robots {
	if (shouldNoIndexDeployment()) {
		return {
			rules: {
				userAgent: "*",
				disallow: "/",
			},
		};
	}
	const jobSitemapCount = getJobSitemapCount();
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
