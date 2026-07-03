import type { MetadataRoute } from "next";

import {
	getSitemapSearchManifest,
	shouldNoIndexDeployment,
} from "@/lib/jobs-sitemap-data";
import { siteUrl } from "@/lib/shared";

const DOC_ROUTES = [
	"/docs",
	"/docs/cli",
	"/docs/configuration",
	"/docs/data-model",
	"/docs/providers",
	"/docs/operations",
	"/docs/contributing",
	"/explorer",
	"/llms.txt",
	"/llms-full.txt",
];

export default function sitemap(): MetadataRoute.Sitemap {
	if (shouldNoIndexDeployment()) {
		return [];
	}
	const snapshotAt = getSitemapSearchManifest().snapshotAt;
	const lastModified = snapshotAt ? new Date(snapshotAt) : new Date();
	return [
		{
			url: siteUrl,
			lastModified,
			changeFrequency: "daily",
			priority: 0.9,
		},
		...DOC_ROUTES.map((route) => ({
			url: `${siteUrl}${route}`,
			lastModified,
			changeFrequency: "weekly" as const,
			priority: route === "/explorer" ? 0.7 : 0.6,
		})),
	];
}
